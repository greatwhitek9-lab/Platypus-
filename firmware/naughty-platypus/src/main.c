/*
 * Naughty Platypus passive BLE observer
 *
 * This app is intentionally passive: it observes BLE advertisements and prints
 * metadata as newline-delimited JSON for a host-side logger. It does not jam,
 * inject, connect, write GATT characteristics, or perform disruptive actions.
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/printk.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/hci.h>

static atomic_t adv_seen;
static atomic_t scan_errors;

static void device_found(const bt_addr_le_t *addr, int8_t rssi, uint8_t type,
                         struct net_buf_simple *ad)
{
    char addr_str[BT_ADDR_LE_STR_LEN];
    uint32_t ms = k_uptime_get_32();
    unsigned int count;

    bt_addr_le_to_str(addr, addr_str, sizeof(addr_str));
    count = (unsigned int)atomic_inc(&adv_seen) + 1U;

    printk("{\"event\":\"adv\",\"ms\":%u,\"addr\":\"%s\",\"type\":%u,\"rssi\":%d,\"len\":%u,\"count\":%u}\n",
           ms,
           addr_str,
           (unsigned int)type,
           (int)rssi,
           (unsigned int)ad->len,
           count);
}

int main(void)
{
    int err;

    printk("{\"event\":\"boot\",\"name\":\"naughty-platypus\",\"mode\":\"passive-ble-observer\"}\n");

    err = bt_enable(NULL);
    if (err) {
        atomic_inc(&scan_errors);
        printk("{\"event\":\"error\",\"stage\":\"bt_enable\",\"code\":%d}\n", err);
        return 0;
    }

    printk("{\"event\":\"ready\",\"name\":\"naughty-platypus\",\"mode\":\"passive-ble-observer\"}\n");

    err = bt_le_scan_start(BT_LE_SCAN_PASSIVE, device_found);
    if (err) {
        atomic_inc(&scan_errors);
        printk("{\"event\":\"error\",\"stage\":\"bt_le_scan_start\",\"code\":%d}\n", err);
        return 0;
    }

    printk("{\"event\":\"scan\",\"state\":\"on\",\"kind\":\"passive\"}\n");

    while (1) {
        k_sleep(K_SECONDS(10));
        printk("{\"event\":\"stats\",\"ms\":%u,\"adv_seen\":%u,\"scan_errors\":%u}\n",
               k_uptime_get_32(),
               (unsigned int)atomic_get(&adv_seen),
               (unsigned int)atomic_get(&scan_errors));
    }

    return 0;
}
