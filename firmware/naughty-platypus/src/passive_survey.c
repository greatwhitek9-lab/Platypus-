#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gap.h>
#include <zephyr/bluetooth/addr.h>

#include "passive_survey.h"

#define HEX_PREVIEW_BYTES 24
#define NAME_MAX_LEN      48
#define HEX_MAX_LEN       ((HEX_PREVIEW_BYTES * 2) + 1)

struct parsed_ad {
    char name[NAME_MAX_LEN];
    char mfg_hex[HEX_MAX_LEN];
    char svc16_hex[HEX_MAX_LEN];
    uint8_t flags;
    bool has_flags;
    bool has_tx_power;
    int8_t adv_tx_power;
};

static bool survey_running;
static bool scan_cb_registered;
static uint32_t adv_events;

#define NP_ADV_QUEUE_LEN 128

struct np_adv_record {
    bt_addr_le_t addr;
    int8_t rssi;
    uint8_t adv_type;
    uint8_t data_len;
};

K_MSGQ_DEFINE(np_adv_msgq, sizeof(struct np_adv_record), NP_ADV_QUEUE_LEN, 4);

static uint32_t queued_events;
static uint32_t dropped_events;
static uint32_t drained_events;
static uint32_t named_events;
static uint32_t mfg_events;
static uint32_t svc_events;
static int8_t strongest_rssi = -127;
static int8_t weakest_rssi = 127;

static const struct bt_le_scan_param np_scan_param = {
    .type = BT_LE_SCAN_TYPE_PASSIVE,
    .options = BT_LE_SCAN_OPT_NONE,
    .interval = 0x00A0,
    .window = 0x0030,
};

static void safe_copy_name(char *dst, size_t dst_len, const uint8_t *src, uint8_t src_len)
{
    size_t n = MIN((size_t)src_len, dst_len - 1);

    for (size_t i = 0; i < n; i++) {
        char c = (char)src[i];

        if (c == '"' || c == '\\') {
            dst[i] = '_';
        } else if (isprint((unsigned char)c)) {
            dst[i] = c;
        } else {
            dst[i] = '.';
        }
    }

    dst[n] = '\0';
}

static void hex_preview(char *dst, size_t dst_len, const uint8_t *src, uint8_t src_len)
{
    static const char hex[] = "0123456789abcdef";
    size_t n = MIN((size_t)src_len, (dst_len - 1) / 2);
    size_t out = 0;

    for (size_t i = 0; i < n; i++) {
        dst[out++] = hex[(src[i] >> 4) & 0x0f];
        dst[out++] = hex[src[i] & 0x0f];
    }

    dst[out] = '\0';
}

static bool parse_ad_cb(struct bt_data *data, void *user_data)
{
    struct parsed_ad *parsed = user_data;

    switch (data->type) {
    case BT_DATA_FLAGS:
        if (data->data_len >= 1) {
            parsed->flags = data->data[0];
            parsed->has_flags = true;
        }
        break;

    case BT_DATA_NAME_SHORTENED:
    case BT_DATA_NAME_COMPLETE:
        if (parsed->name[0] == '\0' || data->type == BT_DATA_NAME_COMPLETE) {
            safe_copy_name(parsed->name, sizeof(parsed->name),
                           data->data, data->data_len);
        }
        break;

    case BT_DATA_TX_POWER:
        if (data->data_len >= 1) {
            parsed->adv_tx_power = (int8_t)data->data[0];
            parsed->has_tx_power = true;
        }
        break;

    case BT_DATA_MANUFACTURER_DATA:
        if (parsed->mfg_hex[0] == '\0') {
            hex_preview(parsed->mfg_hex, sizeof(parsed->mfg_hex),
                        data->data, data->data_len);
        }
        break;

    case BT_DATA_SVC_DATA16:
        if (parsed->svc16_hex[0] == '\0') {
            hex_preview(parsed->svc16_hex, sizeof(parsed->svc16_hex),
                        data->data, data->data_len);
        }
        break;

    default:
        break;
    }

    return true;
}

static const char *phy_to_str(uint8_t phy)
{
    switch (phy) {
    case BT_GAP_LE_PHY_1M:
        return "1M";
    case BT_GAP_LE_PHY_2M:
        return "2M";
    case BT_GAP_LE_PHY_CODED:
        return "CODED";
    default:
        return "unknown";
    }
}

static void scan_recv(const struct bt_le_scan_recv_info *info, struct net_buf_simple *buf)
{
    struct np_adv_record rec = {0};

    adv_events++;

    if (info == NULL || info->addr == NULL) {
        return;
    }

    rec.addr = *info->addr;
    rec.rssi = info->rssi;
    rec.adv_type = info->adv_type;
    rec.data_len = buf ? (buf->len > 255U ? 255U : (uint8_t)buf->len) : 0U;

    if (info->rssi > strongest_rssi) {
        strongest_rssi = info->rssi;
    }

    if (info->rssi < weakest_rssi) {
        weakest_rssi = info->rssi;
    }

    if (k_msgq_put(&np_adv_msgq, &rec, K_NO_WAIT) == 0) {
        queued_events++;
    } else {
        dropped_events++;
    }
}

static struct bt_le_scan_cb np_scan_callbacks = {
    .recv = scan_recv,
};


static void scan_recv_legacy(const bt_addr_le_t *addr,
                             int8_t rssi,
                             uint8_t adv_type,
                             struct net_buf_simple *buf)
{
    static uint32_t legacy_count;

    ARG_UNUSED(addr);
}

int np_passive_survey_start(void)
{
    int err;

    if (!scan_cb_registered) {
        printk("{\"type\":\"scan_diag\",\"step\":\"register_cb\"}\n");
        bt_le_scan_cb_register(&np_scan_callbacks);
        scan_cb_registered = true;
    }

    if (survey_running) {
        return 0;
    }

    printk("{\"type\":\"scan_diag\",\"step\":\"start\",\"scan_type\":%u,\"interval\":%u,\"window\":%u}\n",
           np_scan_param.type, np_scan_param.interval, np_scan_param.window);
    err = bt_le_scan_start(&np_scan_param, NULL);
    if (err == 0) {
        survey_running = true;
        printk("{\"type\":\"status\",\"tool\":\"ble_passive_survey\",\"scan\":\"on\"}\n");
    }

    return err;
}

int np_passive_survey_stop(void)
{
    int err;

    if (!survey_running) {
        return 0;
    }

    err = bt_le_scan_stop();
    if (err == 0) {
        survey_running = false;
        printk("{\"type\":\"status\",\"tool\":\"ble_passive_survey\",\"scan\":\"off\"}\n");
    }

    return err;
}


int np_passive_survey_drain(void)
{
    struct np_adv_record rec;
    char addr[BT_ADDR_LE_STR_LEN];
    uint32_t drained_now = 0U;

    while (k_msgq_get(&np_adv_msgq, &rec, K_NO_WAIT) == 0) {
        bt_addr_le_to_str(&rec.addr, addr, sizeof(addr));
        drained_events++;
        drained_now++;

        printk("{\"type\":\"adv_summary\","
               "\"addr\":\"%s\","
               "\"rssi\":%d,"
               "\"adv_type\":%u,"
               "\"data_len\":%u,"
               "\"drained_events\":%u}\n",
               addr,
               rec.rssi,
               rec.adv_type,
               rec.data_len,
               drained_events);

        /* Keep serial output bounded so BLE/USB stays stable. */
        if (drained_now >= 32U) {
            break;
        }
    }

    return (int)drained_now;
}

int np_passive_survey_status(void)
{
    printk("{\"type\":\"survey_status\","
           "\"scanning\":%s,"
           "\"adv_events\":%u,"
           "\"named_events\":%u,"
           "\"mfg_events\":%u,"
           "\"svc_events\":%u,"
           "\"strongest_rssi\":%d,"
           "\"weakest_rssi\":%d}\n",
           survey_running ? "true" : "false",
           adv_events,
           named_events,
           mfg_events,
           svc_events,
           strongest_rssi,
           weakest_rssi);

    printk("{\"type\":\"queue_status\","
           "\"queued_events\":%u,"
           "\"dropped_events\":%u,"
           "\"drained_events\":%u,"
           "\"pending\":%u}\n",
           queued_events,
           dropped_events,
           drained_events,
           k_msgq_num_used_get(&np_adv_msgq));

    return 0;
}

int np_passive_survey_reset(void)
{
    adv_events = 0;
    queued_events = 0;
    dropped_events = 0;
    drained_events = 0;
    k_msgq_purge(&np_adv_msgq);
    named_events = 0;
    mfg_events = 0;
    svc_events = 0;
    strongest_rssi = -127;
    weakest_rssi = 127;

    printk("{\"type\":\"status\",\"tool\":\"ble_passive_survey\",\"stats\":\"reset\"}\n");
    return 0;
}

bool np_passive_survey_is_running(void)
{
    return survey_running;
}
