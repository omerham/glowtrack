// Reads / controls macOS "Now Playing" (whatever app is playing: Apple Music,
// a browser tab, Tidal, ...). Loaded into /usr/bin/perl by server/players.py -
// recent macOS only lets Apple-signed programs use this private framework.
//
// Build: clang -dynamiclib -fobjc-arc -framework Foundation mr.m -o libmr.dylib
#import <Foundation/Foundation.h>
#import <dlfcn.h>

typedef void (^InfoCb)(NSDictionary *);
typedef void (^BoolCb)(BOOL);
typedef void (*InfoFn)(dispatch_queue_t, InfoCb);
typedef void (*BoolFn)(dispatch_queue_t, BoolCb);
typedef BOOL (*SendFn)(int, NSDictionary *);
typedef void (^ClientCb)(id);
typedef void (*ClientFn)(dispatch_queue_t, ClientCb);
typedef CFStringRef (*BundleFn)(id);

static void *mr(void) {
    return dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_NOW);
}

static id clean(id v) {
    if ([v isKindOfClass:[NSNumber class]] || [v isKindOfClass:[NSString class]]) return v;
    return nil;
}

// Prints one JSON object describing the current item (set MR_ART=1 to include the cover as base64).
void mr_info(void) {
    void *h = mr();
    InfoFn getInfo = h ? (InfoFn)dlsym(h, "MRMediaRemoteGetNowPlayingInfo") : NULL;
    BoolFn getPlaying = h ? (BoolFn)dlsym(h, "MRMediaRemoteGetNowPlayingApplicationIsPlaying") : NULL;
    if (!getInfo) { printf("{}\n"); return; }

    __block NSDictionary *info = nil;
    __block BOOL playing = NO;
    dispatch_semaphore_t s = dispatch_semaphore_create(0);
    getInfo(dispatch_get_global_queue(0, 0), ^(NSDictionary *d) { info = d; dispatch_semaphore_signal(s); });
    dispatch_semaphore_wait(s, dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC));
    if (getPlaying) {
        dispatch_semaphore_t s2 = dispatch_semaphore_create(0);
        getPlaying(dispatch_get_global_queue(0, 0), ^(BOOL p) { playing = p; dispatch_semaphore_signal(s2); });
        dispatch_semaphore_wait(s2, dispatch_time(DISPATCH_TIME_NOW, 1 * NSEC_PER_SEC));
    }
    if (!info.count) { printf("{}\n"); return; }

    // Which app is it? (bundle id, e.g. com.apple.Music, com.google.Chrome)
    __block NSString *bundle = @"";
    ClientFn getClient = (ClientFn)dlsym(h, "MRMediaRemoteGetNowPlayingClient");
    BundleFn getBundle = (BundleFn)dlsym(h, "MRNowPlayingClientGetBundleIdentifier");
    if (getClient && getBundle) {
        dispatch_semaphore_t s3 = dispatch_semaphore_create(0);
        getClient(dispatch_get_global_queue(0, 0), ^(id client) {
            if (client) bundle = (__bridge NSString *)getBundle(client) ?: @"";
            dispatch_semaphore_signal(s3);
        });
        dispatch_semaphore_wait(s3, dispatch_time(DISPATCH_TIME_NOW, 1 * NSEC_PER_SEC));
    }

    NSString *p = @"kMRMediaRemoteNowPlayingInfo";
    #define K(name) info[[p stringByAppendingString:@name]]
    double elapsed = [clean(K("ElapsedTime")) doubleValue];
    NSDate *ts = K("Timestamp");
    if (playing && [ts isKindOfClass:[NSDate class]]) elapsed += [[NSDate date] timeIntervalSinceDate:ts];
    NSData *art = K("ArtworkData");
    BOOL hasArt = [art isKindOfClass:[NSData class]] && art.length > 0;

    NSMutableDictionary *o = [NSMutableDictionary dictionary];
    o[@"title"] = clean(K("Title")) ?: @"";
    o[@"artist"] = clean(K("Artist")) ?: @"";
    o[@"album"] = clean(K("Album")) ?: @"";
    o[@"duration"] = @([clean(K("Duration")) doubleValue]);
    o[@"pos"] = @(elapsed);
    o[@"playing"] = @(playing);
    o[@"bundle"] = bundle;
    o[@"id"] = [clean(K("ContentItemIdentifier")) description] ?: @"";
    o[@"art_id"] = [clean(K("ArtworkIdentifier")) description] ?: @"";
    o[@"has_art"] = @(hasArt || [clean(K("ArtworkIdentifier")) description].length > 0);
    if (hasArt && getenv("MR_ART")) o[@"art_b64"] = [art base64EncodedStringWithOptions:0];
    NSData *j = [NSJSONSerialization dataWithJSONObject:o options:0 error:nil];
    printf("%s\n", j ? [[[NSString alloc] initWithData:j encoding:NSUTF8StringEncoding] UTF8String] : "{}");
}

// Sends a Now Playing command: MR_CMD = 0 play, 1 pause, 2 toggle, 4 next, 5 previous,
// 24 seek (to MR_POS seconds), 6 / 7 cycle shuffle / repeat.
void mr_cmd(void) {
    void *h = mr();
    SendFn send = h ? (SendFn)dlsym(h, "MRMediaRemoteSendCommand") : NULL;
    const char *c = getenv("MR_CMD");
    if (!send || !c) return;
    int cmd = atoi(c);
    NSDictionary *opts = nil;
    const char *pos = getenv("MR_POS");
    if (cmd == 24 && pos) opts = @{@"kMRMediaRemoteOptionPlaybackPosition": @(atof(pos))};
    send(cmd, opts);
}
