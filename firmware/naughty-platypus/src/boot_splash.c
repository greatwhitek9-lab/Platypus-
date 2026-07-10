#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/display.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include "boot_splash.h"
#include "boot_splash_image.h"

#define NP_SPLASH_ROWS_PER_WRITE 8U
#define NP_TFT_POWER_INIT_PRIORITY 70

struct np_base64_reader {
    size_t position;
    uint32_t accumulator;
    uint8_t bits;
};

struct np_packbits_reader {
    struct np_base64_reader base64;
    uint16_t remaining;
    uint8_t repeated_value;
    bool repeated_run;
    size_t produced;
};

static int np_base64_value(char c)
{
    if (c >= 'A' && c <= 'Z') {
        return c - 'A';
    }
    if (c >= 'a' && c <= 'z') {
        return c - 'a' + 26;
    }
    if (c >= '0' && c <= '9') {
        return c - '0' + 52;
    }
    if (c == '+') {
        return 62;
    }
    if (c == '/') {
        return 63;
    }
    return -EINVAL;
}

static int np_base64_next_byte(struct np_base64_reader *reader, uint8_t *value)
{
    while (reader->bits < 8U) {
        int decoded;
        char c;

        if (reader->position >= np_boot_splash_packbits_b64_len) {
            return -ENODATA;
        }

        c = np_boot_splash_packbits_b64[reader->position++];

        if (c == '=') {
            return -ENODATA;
        }

        decoded = np_base64_value(c);
        if (decoded < 0) {
            return decoded;
        }

        reader->accumulator = (reader->accumulator << 6) | (uint32_t)decoded;
        reader->bits += 6U;
    }

    reader->bits -= 8U;
    *value = (uint8_t)((reader->accumulator >> reader->bits) & 0xffU);

    if (reader->bits == 0U) {
        reader->accumulator = 0U;
    } else {
        reader->accumulator &= BIT_MASK(reader->bits);
    }

    return 0;
}

static int np_packbits_next_index(struct np_packbits_reader *reader, uint8_t *index)
{
    int err;

    while (reader->remaining == 0U) {
        uint8_t control;

        err = np_base64_next_byte(&reader->base64, &control);
        if (err != 0) {
            return err;
        }

        if (control <= 127U) {
            reader->remaining = (uint16_t)control + 1U;
            reader->repeated_run = false;
        } else if (control >= 129U) {
            reader->remaining = 257U - (uint16_t)control;
            reader->repeated_run = true;

            err = np_base64_next_byte(&reader->base64,
                                      &reader->repeated_value);
            if (err != 0) {
                return err;
            }
        } else {
            /* PackBits control byte 128 is a no-op. */
            continue;
        }
    }

    if (reader->repeated_run) {
        *index = reader->repeated_value;
    } else {
        err = np_base64_next_byte(&reader->base64, index);
        if (err != 0) {
            return err;
        }
    }

    reader->remaining--;
    reader->produced++;
    return 0;
}

#if defined(CONFIG_NP_BOOT_SPLASH) && DT_HAS_CHOSEN(zephyr_display)

#define NP_DISPLAY_NODE DT_CHOSEN(zephyr_display)
static const struct device *const np_display = DEVICE_DT_GET(NP_DISPLAY_NODE);

#if DT_HAS_ALIAS(tft_en)
static const struct gpio_dt_spec np_tft_enable =
    GPIO_DT_SPEC_GET(DT_ALIAS(tft_en), gpios);
#define NP_HAS_TFT_ENABLE 1
#else
#define NP_HAS_TFT_ENABLE 0
#endif

#if DT_HAS_ALIAS(tft_led_en)
static const struct gpio_dt_spec np_tft_backlight =
    GPIO_DT_SPEC_GET(DT_ALIAS(tft_led_en), gpios);
#define NP_HAS_TFT_BACKLIGHT 1
#else
#define NP_HAS_TFT_BACKLIGHT 0
#endif

/*
 * The board's ST7789V driver initializes before main(). Power must therefore
 * be enabled before CONFIG_DISPLAY_INIT_PRIORITY (85 by default). Failure here
 * is deliberately non-fatal because the display is optional hardware.
 */
static int np_boot_splash_power_early(void)
{
#if NP_HAS_TFT_BACKLIGHT
    if (gpio_is_ready_dt(&np_tft_backlight)) {
        (void)gpio_pin_configure_dt(&np_tft_backlight, GPIO_OUTPUT_INACTIVE);
    }
#endif

#if NP_HAS_TFT_ENABLE
    if (gpio_is_ready_dt(&np_tft_enable)) {
        if (gpio_pin_configure_dt(&np_tft_enable, GPIO_OUTPUT_ACTIVE) == 0) {
            k_busy_wait(50000);
        }
    }
#endif

    return 0;
}

SYS_INIT(np_boot_splash_power_early, POST_KERNEL, NP_TFT_POWER_INIT_PRIORITY);

bool np_boot_splash_available(void)
{
    return device_is_ready(np_display);
}

int np_boot_splash_show(void)
{
    struct display_capabilities caps;
    struct np_packbits_reader decoder = {0};
    static uint16_t row_buffer[NP_BOOT_SPLASH_WIDTH * NP_SPLASH_ROWS_PER_WRITE];
    struct display_buffer_descriptor desc = {
        .width = NP_BOOT_SPLASH_WIDTH,
        .pitch = NP_BOOT_SPLASH_WIDTH,
    };
    int err;

    if (!device_is_ready(np_display)) {
        printk("{\"type\":\"display_status\",\"boot_splash\":\"skipped\","
               "\"reason\":\"display_not_ready\"}\n");
        return -ENODEV;
    }

    display_get_capabilities(np_display, &caps);

    if (caps.x_resolution != NP_BOOT_SPLASH_WIDTH ||
        caps.y_resolution != NP_BOOT_SPLASH_HEIGHT) {
        printk("{\"type\":\"display_status\",\"boot_splash\":\"skipped\","
               "\"reason\":\"resolution_mismatch\",\"width\":%u,\"height\":%u}\n",
               caps.x_resolution, caps.y_resolution);
        return -ENOTSUP;
    }

    if (caps.current_pixel_format != PIXEL_FORMAT_RGB_565) {
        printk("{\"type\":\"display_status\",\"boot_splash\":\"skipped\","
               "\"reason\":\"pixel_format_mismatch\",\"format\":%u}\n",
               caps.current_pixel_format);
        return -ENOTSUP;
    }

    /*
     * Draw while the backlight remains off so users do not see partially
     * rendered rows. The indexed image is decoded directly into a small
     * eight-row RGB565 working buffer instead of a full framebuffer.
     */
    for (uint16_t y = 0U; y < NP_BOOT_SPLASH_HEIGHT;
         y += NP_SPLASH_ROWS_PER_WRITE) {
        uint16_t rows = MIN((uint16_t)NP_SPLASH_ROWS_PER_WRITE,
                            (uint16_t)(NP_BOOT_SPLASH_HEIGHT - y));
        size_t pixel_count = (size_t)NP_BOOT_SPLASH_WIDTH * rows;

        for (size_t i = 0U; i < pixel_count; i++) {
            uint8_t palette_index;

            err = np_packbits_next_index(&decoder, &palette_index);
            if (err != 0) {
                printk("{\"type\":\"display_status\",\"boot_splash\":\"failed\","
                       "\"stage\":\"decode\",\"pixel\":%u,\"err\":%d}\n",
                       (unsigned int)decoder.produced, err);
                return err;
            }

            row_buffer[i] = np_boot_splash_palette_rgb565[palette_index];
        }

        desc.height = rows;
        desc.buf_size = pixel_count * sizeof(row_buffer[0]);

        err = display_write(np_display, 0U, y, &desc, row_buffer);
        if (err != 0) {
            printk("{\"type\":\"display_status\",\"boot_splash\":\"failed\","
                   "\"stage\":\"write\",\"row\":%u,\"err\":%d}\n", y, err);
            return err;
        }
    }

    if (decoder.produced != NP_BOOT_SPLASH_PIXEL_COUNT) {
        printk("{\"type\":\"display_status\",\"boot_splash\":\"failed\","
               "\"stage\":\"decode_count\",\"pixels\":%u}\n",
               (unsigned int)decoder.produced);
        return -EBADMSG;
    }

    err = display_blanking_off(np_display);
    if (err != 0 && err != -ENOSYS && err != -ENOTSUP) {
        printk("{\"type\":\"display_status\",\"boot_splash\":\"failed\","
               "\"stage\":\"blanking_off\",\"err\":%d}\n", err);
        return err;
    }

#if NP_HAS_TFT_BACKLIGHT
    if (gpio_is_ready_dt(&np_tft_backlight)) {
        err = gpio_pin_set_dt(&np_tft_backlight, 1);
        if (err != 0) {
            printk("{\"type\":\"display_status\",\"boot_splash\":\"failed\","
                   "\"stage\":\"backlight\",\"err\":%d}\n", err);
            return err;
        }
    }
#endif

    printk("{\"type\":\"display_status\",\"boot_splash\":\"shown\","
           "\"width\":%u,\"height\":%u}\n",
           NP_BOOT_SPLASH_WIDTH, NP_BOOT_SPLASH_HEIGHT);
    return 0;
}

#else

bool np_boot_splash_available(void)
{
    return false;
}

int np_boot_splash_show(void)
{
    printk("{\"type\":\"display_status\",\"boot_splash\":\"skipped\","
           "\"reason\":\"disabled_or_no_display_node\"}\n");
    return -ENOTSUP;
}

#endif
