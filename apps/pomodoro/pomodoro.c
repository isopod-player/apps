// SPDX-License-Identifier: GPL-2.0-or-later
/* Pomodoro: a timer for isoPod whose screen is its clock face, in flat colours. The time
   left is the kind's colour and the time gone a deep shade of it, parted by a white hand
   that sweeps from the top round, as a game shows a skill cooling down. A tick for each
   minute runs round the edge of the screen, every fifth longer; a white dial in the middle
   holds what is timed, the time left and how it stands. Focus is coral, a short break
   green, the long break after four focuses indigo; the end of each rings a chime and
   flashes the screen.

   The buttons come as keys (app.json): Return starts and stops, Escape ends the app,
   Backspace starts over, S skips to the next; Left and Right choose what to time and Up and
   Down how long, while it is stopped. The end is kept as the time of day, so a timer goes on
   while isoPod has the app stopped in the background, or after it ended: it is there, or
   done, when the app is back. The chime rings when the time runs out with the app in front;
   one that ran out while it was away is shown, not rung.

   The picture is drawn here, in a buffer of the screen's size, with edges blended by their
   distance (no graphics library); text is Pretendard, isoPod's own, through stb_truetype.
   SDL2, the device's, shows it and plays the chime. */

#include <SDL.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"

#define W 640
#define H 480
#define CX 320.f
#define CY 240.f
#define PI 3.14159265f
#define TAU (2 * PI)

enum Mode { FOCUS, SHORT, LONG, MODES };

enum { W_FOCUS, W_SHORT, W_LONG, W_READY, W_RUNNING, W_PAUSED, W_DONE, W_TODAY, W_HINTS };
static const char *WORDS[2][9] = {
    {"집중", "짧은 휴식", "긴 휴식", "A를 눌러 시작", "진행 중", "멈춤", "끝! 다음은 %s", "오늘 %d번",
     "A 시작·멈춤   B 끝내기   X 처음부터   Y 넘기기   ←→ 종류   ↑↓ 분"},
    {"Focus", "Short break", "Long break", "Press A to start", "Running", "Paused", "Done! Next: %s", "%d today",
     "A start/stop   B quit   X restart   Y skip   ←→ kind   ↑↓ minutes"},
};

typedef struct { float r, g, b; } Rgb;
static Rgb hex(uint32_t c) { return (Rgb){((c >> 16) & 255) / 255.f, ((c >> 8) & 255) / 255.f, (c & 255) / 255.f}; }
/* Each kind: its colour, for the time left, and its shade, for the time gone. */
static const uint32_t COLOR[MODES] = {0xF0604D, 0x23B794, 0x5C6BF0};
static const uint32_t SHADE[MODES] = {0x5C2C28, 0x184A40, 0x282D60};
static const uint32_t PAPER = 0xFFFDF8, INK = 0x23262D, GRAY = 0x8B909A, PALE = 0xDADCE0;

/* --- Drawing ----------------------------------------------------------------------------- */

static uint32_t fb[W * H];
static float angle_of[W * H], radius_of[W * H];       /* each pixel's place round the middle */

static float clampf(float v, float a, float b) { return v < a ? a : v > b ? b : v; }
static float mixf(float a, float b, float t) { return a + (b - a) * t; }
static Rgb mix(Rgb a, Rgb b, float t) { return (Rgb){mixf(a.r, b.r, t), mixf(a.g, b.g, t), mixf(a.b, b.b, t)}; }
static float smooth(float e0, float e1, float x) { float t = clampf((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); }
static float cover(float d) { return clampf(0.5f - d, 0, 1); }
static uint32_t pack(Rgb c) {
    return 0xFF000000u | (uint32_t)(clampf(c.r, 0, 1) * 255 + .5f) << 16 | (uint32_t)(clampf(c.g, 0, 1) * 255 + .5f) << 8 |
           (uint32_t)(clampf(c.b, 0, 1) * 255 + .5f);
}

static void blend(int x, int y, Rgb c, float a) {
    if (a <= 0.002f || x < 0 || y < 0 || x >= W || y >= H) return;
    if (a > 1) a = 1;
    fb[y * W + x] = pack(mix(hex(fb[y * W + x]), c, a));
}

static void fill_circle(float cx, float cy, float r, Rgb c, float alpha) {
    for (int y = (int)(cy - r - 1); y <= (int)(cy + r + 1); y++)
        for (int x = (int)(cx - r - 1); x <= (int)(cx + r + 1); x++)
            blend(x, y, c, alpha * cover(hypotf(x + .5f - cx, y + .5f - cy) - r));
}

static void ring(float cx, float cy, float r, float width, Rgb c, float alpha) {
    for (int y = (int)(cy - r - width); y <= (int)(cy + r + width); y++)
        for (int x = (int)(cx - r - width); x <= (int)(cx + r + width); x++)
            blend(x, y, c, alpha * cover(fabsf(hypotf(x + .5f - cx, y + .5f - cy) - r) - width / 2));
}

static float roundbox_d(float px, float py, float hw, float hh, float r) {
    float qx = fabsf(px) - hw + r, qy = fabsf(py) - hh + r;
    return hypotf(fmaxf(qx, 0), fmaxf(qy, 0)) + fminf(fmaxf(qx, qy), 0) - r;
}

static void fill_roundbox(float cx, float cy, float hw, float hh, float r, Rgb c, float alpha) {
    for (int y = (int)(cy - hh - 1); y <= (int)(cy + hh + 1); y++)
        for (int x = (int)(cx - hw - 1); x <= (int)(cx + hw + 1); x++)
            blend(x, y, c, alpha * cover(roundbox_d(x + .5f - cx, y + .5f - cy, hw, hh, r)));
}

/* A line from (x0, y0) to (x1, y1), `width` across, with a glow `glow` wide around it. */
static void line(float x0, float y0, float x1, float y1, float width, float glow, Rgb c, float alpha) {
    float minx = fminf(x0, x1) - glow - width, maxx = fmaxf(x0, x1) + glow + width;
    float miny = fminf(y0, y1) - glow - width, maxy = fmaxf(y0, y1) + glow + width;
    float dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy;
    for (int y = (int)miny; y <= (int)maxy; y++)
        for (int x = (int)minx; x <= (int)maxx; x++) {
            float px = x + .5f - x0, py = y + .5f - y0, t = clampf((px * dx + py * dy) / len2, 0, 1);
            float d = hypotf(px - t * dx, py - t * dy) - width / 2;
            float a = cover(d);
            if (glow > 0) a = fmaxf(a, 0.35f * (1 - smooth(0, glow, d)));
            blend(x, y, c, alpha * a);
        }
}

/* Where a ray from the middle at angle a (0 at the top, clockwise) meets the rounded
   rectangle the ticks run along. */
#define EDGE_HW 300.f
#define EDGE_HH 220.f
#define EDGE_R 44.f
static void edge_point(float a, float *x, float *y) {
    float dx = sinf(a), dy = -cosf(a), lo = 0, hi = 600;
    for (int i = 0; i < 40; i++) {
        float mid = (lo + hi) / 2;
        if (roundbox_d(dx * mid, dy * mid, EDGE_HW, EDGE_HH, EDGE_R) < 0) lo = mid;
        else hi = mid;
    }
    *x = CX + dx * lo, *y = CY + dy * lo;
}

static void make_tables(void) {
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            float px = x + .5f - CX, py = y + .5f - CY, a = atan2f(px, -py);
            angle_of[y * W + x] = a < 0 ? a + TAU : a;
            radius_of[y * W + x] = hypotf(px, py);
        }
}

/* The face with the fraction `gone` of its time passed: two flat colours, their edge
   blended where it crosses a pixel. */
static void face(enum Mode mode, float gone) {
    uint32_t left = pack(hex(COLOR[mode])), dark = pack(hex(SHADE[mode]));
    Rgb lc = hex(COLOR[mode]), dc = hex(SHADE[mode]);
    float edge = gone * TAU;
    for (int i = 0; i < W * H; i++) {
        if (gone <= 0) { fb[i] = left; continue; }
        if (gone >= 1) { fb[i] = dark; continue; }
        float a = angle_of[i], dist = a < edge ? fminf(a, edge - a) : -fminf(a - edge, TAU - a);
        float in = clampf(0.5f + dist * radius_of[i], 0, 1);
        fb[i] = in <= 0 ? left : in >= 1 ? dark : pack(mix(lc, dc, in));
    }
}

/* --- Text -------------------------------------------------------------------------------- */

typedef struct { stbtt_fontinfo info; unsigned char *data; } Font;
static Font bold, medium;

static int load_font(Font *f, const char *name) {
    const char *dirs[] = {getenv("POMODORO_FONTS"), "/usr/share/isopod/fonts", "share/fonts"};
    for (size_t i = 0; i < 3; i++) {
        if (!dirs[i]) continue;
        char path[512];
        snprintf(path, sizeof path, "%s/%s", dirs[i], name);
        FILE *fp = fopen(path, "rb");
        if (!fp) continue;
        fseek(fp, 0, SEEK_END);
        long n = ftell(fp);
        fseek(fp, 0, SEEK_SET);
        f->data = malloc(n);
        if (fread(f->data, 1, n, fp) == (size_t)n &&
            stbtt_InitFont(&f->info, f->data, stbtt_GetFontOffsetForIndex(f->data, 0))) {
            fclose(fp);
            return 1;
        }
        fclose(fp);
        free(f->data);
        f->data = NULL;
    }
    fprintf(stderr, "pomodoro: no font %s\n", name);
    return 0;
}

static int utf8(const char **s) {
    const unsigned char *p = (const unsigned char *)*s;
    int c = *p, n = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
    c = n == 1 ? c : n == 2 ? c & 31 : n == 3 ? c & 15 : c & 7;
    for (int i = 1; i < n && p[i]; i++) c = c << 6 | (p[i] & 63);
    *s += n;
    return c;
}

static float text_width(Font *f, float size, const char *s) {
    if (!f->data) return 0;
    float scale = stbtt_ScaleForPixelHeight(&f->info, size), w = 0;
    int prev = 0;
    while (*s) {
        int c = utf8(&s), adv, lsb;
        stbtt_GetCodepointHMetrics(&f->info, c, &adv, &lsb);
        if (prev) w += scale * stbtt_GetCodepointKernAdvance(&f->info, prev, c);
        w += scale * adv;
        prev = c;
    }
    return w;
}

/* Text centred on x, its baseline at y. */
static void text(Font *f, float size, const char *s, float x, float y, Rgb c, float alpha) {
    if (!f->data) return;
    float scale = stbtt_ScaleForPixelHeight(&f->info, size), pen = x - text_width(f, size, s) / 2;
    int prev = 0;
    while (*s) {
        int ch = utf8(&s), adv, lsb, x0, y0, x1, y1;
        if (prev) pen += scale * stbtt_GetCodepointKernAdvance(&f->info, prev, ch);
        stbtt_GetCodepointHMetrics(&f->info, ch, &adv, &lsb);
        float sub = pen - floorf(pen);
        stbtt_GetCodepointBitmapBoxSubpixel(&f->info, ch, scale, scale, sub, 0, &x0, &y0, &x1, &y1);
        int gw = x1 - x0, gh = y1 - y0;
        if (gw > 0 && gh > 0) {
            unsigned char *g = malloc(gw * gh);
            stbtt_MakeCodepointBitmapSubpixel(&f->info, g, gw, gh, gw, scale, scale, sub, 0, ch);
            for (int j = 0; j < gh; j++)
                for (int i = 0; i < gw; i++)
                    blend((int)floorf(pen) + x0 + i, (int)y + y0 + j, c, alpha * g[j * gw + i] / 255.f);
            free(g);
        }
        pen += scale * adv;
        prev = ch;
    }
}

/* --- Sound ------------------------------------------------------------------------------- */

static SDL_AudioDeviceID audio;

/* Two bell notes, a fifth apart, each fading. */
static void chime(void) {
    if (!audio) return;
    enum { RATE = 48000, LEN = RATE * 2 };
    static float buf[LEN];
    const float notes[2] = {1046.5f, 1568.0f};
    for (int i = 0; i < LEN; i++) {
        float t = (float)i / RATE, v = 0;
        for (int n = 0; n < 2; n++) {
            float s = t - n * 0.28f;
            if (s < 0) continue;
            float env = expf(-3.2f * s) * fminf(1, s * 200);
            v += env * (sinf(TAU * notes[n] * s) + 0.35f * sinf(TAU * notes[n] * 2.76f * s) * expf(-6 * s));
        }
        buf[i] = 0.22f * v;
    }
    SDL_ClearQueuedAudio(audio);
    SDL_QueueAudio(audio, buf, sizeof buf);
}

/* --- The timer --------------------------------------------------------------------------- */

typedef struct {
    enum Mode mode;
    int minutes[MODES];
    int running;
    double remaining; /* seconds, while stopped */
    double end;       /* the time of day it runs out, while running */
    int done;         /* focus sessions in this round of four */
    int today, day;   /* focus sessions finished today, and which day that is */
    int finished;     /* the last one ran out (not skipped): say so until the next starts */
    double flash;     /* when it last ran out, for the flash */
} Timer;

static Timer tm = {FOCUS, {25, 5, 15}, 0, 25 * 60, 0, 0, 0, -1, 0, -100};
static char state_path[512];

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static int today(void) {
    time_t t = time(NULL);
    struct tm lt;
    localtime_r(&t, &lt);
    return lt.tm_year * 1000 + lt.tm_yday;
}

static void save(void) {
    FILE *f = fopen(state_path, "w");
    if (!f) return;
    fprintf(f, "mode %d\nfocus %d\nshort %d\nlong %d\nrunning %d\nremaining %.3f\nend %.3f\ndone %d\ntoday %d\nday %d\n",
            tm.mode, tm.minutes[FOCUS], tm.minutes[SHORT], tm.minutes[LONG], tm.running, tm.remaining, tm.end,
            tm.done, tm.today, tm.day);
    fclose(f);
}

static void load(void) {
    FILE *f = fopen(state_path, "r");
    if (!f) return;
    char key[32];
    double v;
    while (fscanf(f, "%31s %lf", key, &v) == 2) {
        if (!strcmp(key, "mode") && v >= 0 && v < MODES) tm.mode = (enum Mode)v;
        else if (!strcmp(key, "focus") && v >= 1 && v <= 120) tm.minutes[FOCUS] = (int)v;
        else if (!strcmp(key, "short") && v >= 1 && v <= 60) tm.minutes[SHORT] = (int)v;
        else if (!strcmp(key, "long") && v >= 1 && v <= 90) tm.minutes[LONG] = (int)v;
        else if (!strcmp(key, "running")) tm.running = v != 0;
        else if (!strcmp(key, "remaining") && v >= 0) tm.remaining = v;
        else if (!strcmp(key, "end")) tm.end = v;
        else if (!strcmp(key, "done") && v >= 0 && v < 4) tm.done = (int)v;
        else if (!strcmp(key, "today")) tm.today = (int)v;
        else if (!strcmp(key, "day")) tm.day = (int)v;
    }
    fclose(f);
}

static double left(void) { return tm.running ? fmax(0, tm.end - now()) : tm.remaining; }
static double full(void) { return tm.minutes[tm.mode] * 60.0; }

static void choose(enum Mode mode) {
    tm.mode = mode;
    tm.running = 0;
    tm.remaining = full();
}

/* The time ran out (or was skipped): on to the next, a long break after four focuses. */
static void next(int ran_out) {
    if (ran_out) {
        if (tm.mode == FOCUS) {
            if (tm.day != today()) tm.day = today(), tm.today = 0;
            tm.today++;
            tm.done++;
        }
        if (now() - tm.end < 3) chime();  /* not for an end found only when the app came back */
        tm.flash = now();
    }
    enum Mode after = FOCUS;
    if (tm.mode == FOCUS) after = tm.done >= 4 ? LONG : SHORT;
    if (tm.mode == LONG) tm.done = 0;
    choose(after);
    tm.finished = ran_out;
    save();
}

/* A key: whether the app should end. */
static int press(SDL_Keycode key) {
    switch (key) {
    case SDLK_ESCAPE:
        return 1;
    case SDLK_RETURN: case SDLK_SPACE: case SDLK_KP_ENTER:
        if (tm.running) tm.remaining = left(), tm.running = 0;
        else tm.end = now() + tm.remaining, tm.running = 1, tm.finished = 0;
        break;
    case SDLK_BACKSPACE:
        tm.running = 0, tm.remaining = full(), tm.finished = 0;
        break;
    case SDLK_s: case SDLK_TAB:
        next(0);
        break;
    case SDLK_LEFT: case SDLK_RIGHT:
        if (!tm.running) choose((enum Mode)((tm.mode + (key == SDLK_RIGHT ? 1 : MODES - 1)) % MODES)), tm.finished = 0;
        break;
    case SDLK_UP: case SDLK_DOWN: {
        static const int LIMIT[MODES][2] = {{5, 120}, {1, 60}, {5, 90}};
        if (tm.running) break;
        int *m = &tm.minutes[tm.mode], step = *m >= 10 && tm.mode != SHORT ? 5 : 1;
        if (key == SDLK_DOWN && *m == 10 && tm.mode != SHORT) step = 1;
        *m = key == SDLK_UP ? *m + step : *m - step;
        *m = *m < LIMIT[tm.mode][0] ? LIMIT[tm.mode][0] : *m > LIMIT[tm.mode][1] ? LIMIT[tm.mode][1] : *m;
        tm.remaining = full(), tm.finished = 0;
        break;
    }
    default:
        return 0;
    }
    save();
    return 0;
}

/* --- One picture -------------------------------------------------------------------------- */

static void draw(int lang, double t) {
    const char **w = WORDS[lang];
    Rgb white = hex(0xFFFFFF), color = hex(COLOR[tm.mode]);
    Rgb paper = hex(PAPER), ink = hex(INK), gray = hex(GRAY), pale = hex(PALE);
    double l = left();
    float gone = (float)(1 - l / full()), edge = gone * TAU;
    int stopped = !tm.running, part_way = stopped && l < full() - 0.5;
    face(tm.mode, gone);

    /* A tick for each minute round the edge, every fifth longer, fainter over the time gone. */
    int minutes = tm.minutes[tm.mode], ticks = minutes <= 60 ? minutes : (minutes + 1) / 2;
    for (int k = 0; k < ticks; k++) {
        float a = k * TAU / ticks, x, y;
        edge_point(a, &x, &y);
        int major = k % 5 == 0;
        float len = major ? 18 : 9, dx = sinf(a), dy = -cosf(a);
        line(x - dx * len, y - dy * len, x, y, major ? 4 : 2.5f, 0, white, a >= edge ? 0.9f : 0.3f);
    }

    /* The hand, from the dial out to the edge. */
    if (gone > 0.0005f && gone < 0.9995f) {
        float x, y;
        edge_point(edge, &x, &y);
        float pulse = part_way ? 0.55f + 0.45f * sinf((float)t * 3) : 1;
        line(CX + sinf(edge) * 128, CY - cosf(edge) * 128, x, y, 4, 0, white, pulse);
    }

    /* The dial: what is timed, the time, how it stands, and this round of four focuses. */
    fill_circle(CX, CY, 126, paper, 1);
    text(&medium, 22, w[W_FOCUS + tm.mode], CX, CY - 60, color, 1);
    char clock[16], status[96];
    int secs = (int)ceil(l);
    snprintf(clock, sizeof clock, "%02d:%02d", secs / 60, secs % 60);
    float breath = part_way ? 0.55f + 0.45f * sinf((float)t * 3) : 1;
    text(&bold, 94, clock, CX, CY + 33, ink, breath);
    if (tm.finished) snprintf(status, sizeof status, w[W_DONE], w[W_FOCUS + tm.mode]);
    else if (tm.running) snprintf(status, sizeof status, "%s", w[W_RUNNING]);
    else if (part_way) snprintf(status, sizeof status, "%s", w[W_PAUSED]);
    else snprintf(status, sizeof status, "%s", w[W_READY]);
    text(&medium, 17, status, CX, CY + 67, gray, 1);
    for (int i = 0; i < 4; i++) {
        float x = CX - 33 + i * 22, y = CY + 90;
        if (i < tm.done) fill_circle(x, y, 6, hex(COLOR[FOCUS]), 1);
        else ring(x, y, 5, 2, pale, 1);
    }

    /* Stopped: the kinds along the top, the buttons along the bottom, and today's count. */
    if (stopped) {
        for (int m = 0; m < MODES; m++) {
            char label[64];
            snprintf(label, sizeof label, "%s %d", w[W_FOCUS + m], tm.minutes[m]);
            float x = CX + (m - 1) * 170, half = text_width(&medium, 16, label) / 2 + 14;
            int on = m == (int)tm.mode;
            if (on) fill_roundbox(x, 44, half, 15, 15, paper, 1);
            text(&medium, 16, label, x, 50, on ? color : white, on ? 1 : 0.85f);
        }
        float half = text_width(&medium, 13, w[W_HINTS]) / 2 + 14;
        fill_roundbox(CX, 446, half, 14, 14, ink, 1);
        text(&medium, 13, w[W_HINTS], CX, 451, white, 0.9f);
        char count[32];
        snprintf(count, sizeof count, w[W_TODAY], tm.day == today() ? tm.today : 0);
        text(&medium, 14, count, CX, CY + 113, gray, 1);
    }

    /* Ran out: the screen flashes. */
    double since = t - tm.flash;
    if (since >= 0 && since < 0.9) {
        float a = 0.55f * (1 - (float)since / 0.9f);
        for (int i = 0; i < W * H; i++) fb[i] = pack(mix(hex(fb[i]), white, a * a));
    }
}

int main(int argc, char **argv) {
    (void)argc, (void)argv;
    const char *data = getenv("ISOPOD_APP_DATA") ? getenv("ISOPOD_APP_DATA") : getenv("HOME");
    snprintf(state_path, sizeof state_path, "%s/pomodoro.txt", data ? data : ".");
    int lang = getenv("ISOPOD_LANG") && !strcmp(getenv("ISOPOD_LANG"), "en") ? 1 : 0;
    load();
    if (!tm.running && tm.remaining > full()) tm.remaining = full();
    make_tables();
    load_font(&bold, "Pretendard-Bold.otf");
    load_font(&medium, "Pretendard-SemiBold.otf");

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "pomodoro: %s\n", SDL_GetError());
        return 1;
    }
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) == 0) {
        SDL_AudioSpec want = {.freq = 48000, .format = AUDIO_F32SYS, .channels = 1, .samples = 1024}, have;
        audio = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
        if (audio) SDL_PauseAudioDevice(audio, 0);
    }
    SDL_Window *win = SDL_CreateWindow("Pomodoro", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, W, H,
                                       SDL_WINDOW_FULLSCREEN_DESKTOP);
    SDL_Renderer *ren = win ? SDL_CreateRenderer(win, -1, 0) : NULL;
    if (!ren) {
        fprintf(stderr, "pomodoro: %s\n", SDL_GetError());
        return 1;
    }
    SDL_RenderSetLogicalSize(ren, W, H);
    SDL_Texture *tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, W, H);
    SDL_ShowCursor(SDL_DISABLE);

    for (int quit = 0; !quit;) {
        double t = now();
        if (tm.running && left() <= 0) next(1);
        draw(lang, t);
        SDL_UpdateTexture(tex, NULL, fb, W * 4);
        SDL_RenderClear(ren);
        SDL_RenderCopy(ren, tex, NULL, NULL);
        SDL_RenderPresent(ren);
        /* Busy only while something moves: 30 frames a second for a flash, ten for the
           breath of a paused clock, four while counting down, and then only for a press. */
        double l = left(), since = t - tm.flash;
        int wait = since < 0.9 ? 33 : !tm.running && l < full() - 0.5 ? 100 : tm.running ? 250 : 1000;
        SDL_Event ev;
        if (SDL_WaitEventTimeout(&ev, wait)) do {
            if (ev.type == SDL_QUIT) quit = 1;
            else if (ev.type == SDL_KEYDOWN && !ev.key.repeat) quit |= press(ev.key.keysym.sym);
            else if (ev.type == SDL_KEYDOWN && (ev.key.keysym.sym == SDLK_UP || ev.key.keysym.sym == SDLK_DOWN))
                press(ev.key.keysym.sym);
        } while (SDL_PollEvent(&ev));
    }
    save();
    SDL_Quit();
    return 0;
}
