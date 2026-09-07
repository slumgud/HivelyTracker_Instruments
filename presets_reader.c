/* Minimal C reference reader for presets.bin v1.  No SQLite or project code. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t le16(const unsigned char *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }

int main(int argc, char **argv) {
    FILE *f; long length; unsigned char *data; size_t p, records_end, i;
    uint16_t version; uint32_t count, strings;
    if (argc != 2) { fprintf(stderr, "usage: %s presets.bin\n", argv[0]); return 2; }
    f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); length = ftell(f); fseek(f, 0, SEEK_SET);
    if (length < 16) { fprintf(stderr, "truncated header\n"); fclose(f); return 1; }
    data = (unsigned char *)malloc((size_t)length); if (!data) { fclose(f); return 2; }
    if (fread(data, 1, (size_t)length, f) != (size_t)length) { free(data); fclose(f); return 2; }
    fclose(f);
    if (memcmp(data, "AHXP", 4) != 0 || (version = le16(data + 4)) != 1) {
        fprintf(stderr, "unsupported AHXP header/version\n"); free(data); return 1;
    }
    count = le32(data + 8); strings = le32(data + 12);
    if ((uint64_t)strings > (uint64_t)length - 16) { fprintf(stderr, "invalid string table\n"); free(data); return 1; }
    records_end = (size_t)length - strings; p = 16;
    for (i = 0; i < count; ++i) {
        uint32_t name_offset, payload_size;
        if (p + 32 > records_end) { fprintf(stderr, "truncated record %zu\n", i); free(data); return 1; }
        name_offset = le32(data + p); payload_size = le32(data + p + 4); p += 32;
        if (p + payload_size > records_end || name_offset >= strings) { fprintf(stderr, "invalid record %zu\n", i); free(data); return 1; }
        if (memchr(data + records_end + name_offset, 0, strings - name_offset) == NULL) { fprintf(stderr, "unterminated name\n"); free(data); return 1; }
        p += payload_size;
    }
    if (p != records_end) { fprintf(stderr, "record boundary mismatch\n"); free(data); return 1; }
    printf("presets.bin v%u: %u records, %u string bytes\n", version, count, strings);
    free(data); return 0;
}
