int np_passive_survey_drain(void);

#include <zephyr/drivers/uart.h>
#include <zephyr/devicetree.h>
#include <zephyr/device.h>
#include <errno.h>
#include <stdio.h>

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/shell/shell.h>
#include <zephyr/bluetooth/bluetooth.h>

#if defined(CONFIG_USB_DEVICE_STACK)
#include <zephyr/usb/usb_device.h>
#endif

#include "passive_survey.h"
#include "tool_registry.h"

static bool bt_ready;

static int cmd_scan_on(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    int err = np_passive_survey_start();

    if (err) {
        shell_error(sh, "scan_on failed: %d", err);
        return err;
    }

    shell_print(sh, "passive BLE survey started");
    return 0;
}

static int cmd_scan_off(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    int err = np_passive_survey_stop();

    if (err) {
        shell_error(sh, "scan_off failed: %d", err);
        return err;
    }

    shell_print(sh, "passive BLE survey stopped");
    return 0;
}

static int cmd_status(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    shell_print(sh, "bt_ready=%s survey_running=%s",
                bt_ready ? "yes" : "no",
                np_passive_survey_is_running() ? "yes" : "no");

    return np_passive_survey_status();
}

static int cmd_reset_stats(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    shell_print(sh, "survey counters reset");
    return np_passive_survey_reset();
}

static int cmd_tools_list(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    uint32_t count = 0;
    const struct np_tool *tools = np_tools_get(&count);

    for (uint32_t i = 0; i < count; i++) {
        shell_print(sh,
                    "%s | enabled=%s | risk=%s | status=%s | %s",
                    tools[i].id,
                    tools[i].enabled ? "true" : "false",
                    np_risk_to_str(tools[i].risk),
                    np_status_to_str(tools[i].status),
                    tools[i].description);
    }

    return 0;
}

static int cmd_tools_run(const struct shell *sh, size_t argc, char **argv)
{
    if (argc < 2) {
        shell_error(sh, "usage: np tools_run <tool_id>");
        return -EINVAL;
    }

    int err = np_tool_run_by_id(argv[1]);

    if (err == -EPERM) {
        shell_error(sh, "tool disabled by build config: %s", argv[1]);
    } else if (err == -ENOTSUP) {
        shell_error(sh, "tool is stub-only / not implemented: %s", argv[1]);
    } else if (err == -ENOENT) {
        shell_error(sh, "unknown tool: %s", argv[1]);
    } else if (err) {
        shell_error(sh, "tool failed: %d", err);
    }

    return err;
}

SHELL_STATIC_SUBCMD_SET_CREATE(sub_np,
    SHELL_CMD(scan_on, NULL, "Start passive BLE advertisement survey", cmd_scan_on),
    SHELL_CMD(scan_off, NULL, "Stop passive BLE advertisement survey", cmd_scan_off),
    SHELL_CMD(status, NULL, "Show survey status and counters", cmd_status),
    SHELL_CMD(reset_stats, NULL, "Reset survey counters", cmd_reset_stats),
    SHELL_CMD(tools_list, NULL, "List safe and restricted tool registry", cmd_tools_list),
    SHELL_CMD(tools_run, NULL, "Run enabled tool by ID", cmd_tools_run),
    SHELL_SUBCMD_SET_END
);

SHELL_CMD_REGISTER(np, &sub_np, "Naughty Platypus lab commands", NULL);


static void np_cdc_write(const char *s)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(board_cdc_acm_uart), okay)
    const struct device *dev = DEVICE_DT_GET(DT_NODELABEL(board_cdc_acm_uart));

    if (!device_is_ready(dev) || s == NULL) {
        return;
    }

#if defined(CONFIG_UART_LINE_CTRL)
    uint32_t dtr = 0;

    for (int i = 0; i < 40; i++) {
        if (uart_line_ctrl_get(dev, UART_LINE_CTRL_DTR, &dtr) == 0 && dtr) {
            break;
        }
        k_sleep(K_MSEC(50));
    }
#endif

    while (*s) {
        uart_poll_out(dev, (unsigned char)*s++);
    }
#else
    ARG_UNUSED(s);
#endif
}

static void np_cdc_write_u32(const char *prefix, uint32_t value, const char *suffix)
{
    char buf[128];

    snprintk(buf, sizeof(buf), "%s%u%s", prefix, value, suffix);
    np_cdc_write(buf);
}


static int cmd_np_version_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    shell_print(sh, "{\"type\":\"version\",\"app\":\"naughty-platypus\",\"build\":\"oneword_cmds_v1\",\"mode\":\"passive_ble_survey\"}");
    return 0;
}

static int cmd_np_status_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(sh);
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    return np_passive_survey_status();
}

static int cmd_np_survey_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(sh);
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    np_passive_survey_drain();
    return np_passive_survey_status();
}

static int cmd_np_scan_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(sh);
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    return np_passive_survey_start();
}

static int cmd_np_stop_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(sh);
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    return np_passive_survey_stop();
}

static int cmd_np_reset_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(sh);
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    return np_passive_survey_reset();
}

static int cmd_np_commands_oneword(const struct shell *sh, size_t argc, char **argv)
{
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);

    shell_print(sh, "version");
    shell_print(sh, "status");
    shell_print(sh, "survey");
    shell_print(sh, "scan");
    shell_print(sh, "stop");
    shell_print(sh, "reset");
    shell_print(sh, "commands");
    return 0;
}

SHELL_CMD_REGISTER(version, NULL, "Show Naughty Platypus firmware version.", cmd_np_version_oneword);
SHELL_CMD_REGISTER(status, NULL, "Show BLE survey counters.", cmd_np_status_oneword);
SHELL_CMD_REGISTER(survey, NULL, "Drain BLE queue and show counters.", cmd_np_survey_oneword);
SHELL_CMD_REGISTER(scan, NULL, "Start passive BLE survey.", cmd_np_scan_oneword);
SHELL_CMD_REGISTER(stop, NULL, "Stop passive BLE survey.", cmd_np_stop_oneword);
SHELL_CMD_REGISTER(reset, NULL, "Reset BLE survey counters.", cmd_np_reset_oneword);
SHELL_CMD_REGISTER(commands, NULL, "List one-word Naughty Platypus commands.", cmd_np_commands_oneword);


int main(void)
{
    np_cdc_write("\r\n{\"type\":\"serial_boot\",\"app\":\"naughty-platypus\",\"path\":\"direct_cdc\"}\r\n");
    np_cdc_write("{\"type\":\"firmware_marker\",\"build\":\"oneword_cmds_v1\"}\r\n");
    int err;


#if defined(CONFIG_USB_DEVICE_STACK)
    err = usb_enable(NULL);
    if (err && err != -EALREADY) {
        printk("{\"type\":\"error\",\"where\":\"usb_enable\",\"err\":%d}\n", err);
    }
#endif

    printk("\n");
    printk("Naughty Platypus Ubertooth-Style BLE Lab Suite\n");
    printk("{\"type\":\"boot\",\"app\":\"naughty-platypus\",\"role\":\"passive_ble_lab_suite\"}\n");

    err = bt_enable(NULL);
    if (err) {
        printk("{\"type\":\"error\",\"where\":\"bt_enable\",\"err\":%d}\n", err);
        return 0;
    }

    bt_ready = true;

    printk("{\"type\":\"status\",\"bluetooth\":\"ready\",\"hint\":\"run np tools_list or np scan_on\"}\n");

    int scan_err = np_passive_survey_start();
    np_cdc_write_u32("{\"path\":\"direct_cdc\",\"type\":\"scan_start\",\"err\":", scan_err, "}\r\n");

    /* auto_survey_status_loop: print counters without needing shell RX */
    while (1) {
        k_sleep(K_SECONDS(3));
        np_passive_survey_drain();
        np_passive_survey_status();
    }
    char scan_msg[128];
    snprintk(scan_msg, sizeof(scan_msg),
             "{\"path\":\"direct_cdc\",\"type\":\"scan_start\",\"err\":%d}\r\n",
             scan_err);
    np_cdc_write(scan_msg);

    while (1) {
        k_sleep(K_SECONDS(2));
        printk("{\"type\":\"heartbeat\",\"uptime_ms\":%u,\"survey_running\":%s}\n",
               k_uptime_get_32(),
               np_passive_survey_is_running() ? "true" : "false");
    }

    return 0;
}
