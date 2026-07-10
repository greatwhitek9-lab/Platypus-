#ifndef NAUGHTY_PLATYPUS_BOOT_SPLASH_IMAGE_H
#define NAUGHTY_PLATYPUS_BOOT_SPLASH_IMAGE_H

#include <stddef.h>
#include <stdint.h>

#define NP_BOOT_SPLASH_WIDTH  135U
#define NP_BOOT_SPLASH_HEIGHT 240U
#define NP_BOOT_SPLASH_PALETTE_SIZE 256U
#define NP_BOOT_SPLASH_PIXEL_COUNT (NP_BOOT_SPLASH_WIDTH * NP_BOOT_SPLASH_HEIGHT)

extern const uint16_t np_boot_splash_palette_rgb565[NP_BOOT_SPLASH_PALETTE_SIZE];
extern const char np_boot_splash_packbits_b64[];
extern const size_t np_boot_splash_packbits_b64_len;

#endif
