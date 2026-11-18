import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { gzipSync } from 'node:zlib';

const [stage, external] = process.argv.slice(2);
const scripts = path.join(stage, 'scripts');
for (const directory of [scripts, external]) {
    for (const file of readdirSync(directory)) {
        new vm.Script(readFileSync(path.join(directory, file), 'utf8'), { filename: file });
    }
}

async function run(file, globals, directory = scripts) {
    const logs = [];
    const completions = [];
    const sandbox = {
        URL, URLSearchParams, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer,
        navigator: { userAgent: 'iPhone' },
        $environment: { 'stash-version': '3.7', system: 'iOS', language: 'zh-Hans' },
        $persistentStore: { read: () => null, write: () => true },
        $notification: { post() {} },
        console: { info: (...args) => logs.push(args), warn: (...args) => logs.push(args), debug: (...args) => logs.push(args), log: (...args) => logs.push(args), error: (...args) => logs.push(args) },
        $done: (...args) => completions.push(args),
        ...globals,
    };
    const script = new vm.Script(readFileSync(path.join(directory, file), 'utf8'), { filename: file });
    script.runInNewContext(sandbox, { timeout: 3000 });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(completions.length, 1, JSON.stringify(logs));
    assert.equal(logs.filter(args => args[0] instanceof Error || String(args[0]).includes("ERROR")).length, 0, logs.flat().map(String).join("\n"));
    return completions[0];
}

const server = 'https://grpc.biliapi.net/bilibili.';
const grpc = (body, compressed = false) => {
    const payload = compressed ? gzipSync(Buffer.from(body)) : Buffer.from(body);
    const frame = Buffer.alloc(payload.length + 5);
    frame[0] = Number(compressed);
    frame.writeUInt32BE(payload.length, 1);
    payload.copy(frame, 5);
    return Uint8Array.from(frame);
};
const item = text => [34, text.length + 2, 34, text.length, ...Buffer.from(text)];
const kept = item('video');
const search = {
    url: server + 'polymer.app.search.v1.Search/SearchAll',
    method: 'POST',
    headers: { te: 'trailers' },
};
for (const compressed of [false, true]) {
    const [result] = await run('bilibili.protobuf.response.js', {
        $request: search,
        $response: { status: 200, headers: {}, body: grpc([...item('video_ad_'), ...kept], compressed) },
    });
    assert.deepEqual(result.body, grpc(kept));
    assert.equal(result.headers['grpc-status'], '0');
}

const progress = {
    url: server + 'app.viewunite.v1.View/ViewProgress',
    method: 'POST',
    headers: { 'user-agent': 'bili-universal/91700000', te: 'trailers' },
    body: grpc([8, 1, 16, 2], true),
};
for (const enabled of [true, false]) {
    const calls = [];
    const [result] = await run('bilibili.protobuf.request.js', {
        $request: progress,
        $argument: JSON.stringify({ enabled }),
        $httpClient: {
            post(request, callback) {
                calls.push(request.url);
                assert.equal(request['binary-mode'], true);
                assert.deepEqual(request.body, progress.body);
                callback(null, { status: 200, headers: {}, trailers: { 'grpc-status': '0', 'grpc-message': '' } }, grpc([]));
            },
            get(request, callback) {
                calls.push(request.url);
                assert.match(request.url, /^https:\/\/bsbsb\.top\/api\/skipSegments\?videoID=BV[^&]+&cid=2&category=sponsor$/);
                callback(null, { status: 200, headers: {} },
                    JSON.stringify([{ actionType: 'skip', segment: [7, 20], videoDuration: 60 }]));
            },
        },
    });
    if (enabled) {
        assert.equal(calls.length, 2);
        assert.equal(result.response.headers['grpc-status'], '0');
        assert.equal(result.response.headers['grpc-message'], '');
        const body = Buffer.from(result.response.body);
        assert.equal(body.readUInt32BE(1), body.length - 5);
        assert.ok(body.includes(Buffer.from('广告')));
    } else {
        assert.equal(calls.length, 0);
        assert.equal(Object.keys(result).length, 0);
    }
}

const [feed] = await run('bilibili.json.js', {
    $request: { url: 'https://app.bilibili.com/x/v2/feed/index?', method: 'GET', headers: {} },
    $response: { status: 200, headers: { 'bili-status-code': '0' }, body: JSON.stringify({ code: 0, data: { items: [
        { card_goto: 'av', card_type: 'small_cover_v2', id: 1 },
        { card_goto: 'av', card_type: 'small_cover_v2', id: 2, ad_info: {} },
    ] } }) },
});
assert.deepEqual(JSON.parse(feed.body).data.items.map(item => item.id), [1]);

const creatorSections = [];
for (const showCreatorHub of [false, true]) {
    const [account] = await run('bilibili.json.js', {
        $request: { url: 'https://app.bilibili.com/x/v2/account/mine?', method: 'GET', headers: {} },
        $response: { status: 200, headers: { 'bili-status-code': '0' }, body: JSON.stringify({ code: 0, data: { sections_v2: [] } }) },
        $argument: JSON.stringify({ showCreatorHub }),
    });
    creatorSections.push(JSON.parse(account.body).data.sections_v2.length);
}
assert.equal(creatorSections[1], creatorSections[0] + 1);

const [adList] = await run('12306.js', {
    $request: { url: 'https://ad.12306.cn/ad/ser/getAdList', method: 'POST', headers: {}, body: '{"placementNo":"0007"}' },
});
assert.equal(JSON.parse(adList.response.body).advertParam.skipTime, 1);
assert.deepEqual(await run('12306.js', {
    $request: { url: 'https://mobile.12306.cn/otsmobile/app/mgs/mgw.htm', method: 'POST',
        headers: { 'operation-type': 'com.cars.otsmobile.newHomePageBussData' } },
}), []);

const [skin] = await run('bili-suit-diy.js', {
    $response: { body: '{"data":{"common_equip":true}}' },
    $httpClient: {},
    $persistentStore: { read: key => ({ bili_user_equip: '[{"id":123}]', bili_skin_num: '1' })[key] },
}, external);
assert.deepEqual(JSON.parse(skin.body).data, { user_equip: { id: 123 } });
console.log('Passed Stash API fixtures for gzip/plain protobuf, SponsorBlock, gRPC headers, ads, and preferences.');
