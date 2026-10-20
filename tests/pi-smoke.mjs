// Run with PI_SDK_PATH pointing at the installed package directory.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const sdk = process.env.PI_SDK_PATH;
if (!sdk) throw new Error('Set PI_SDK_PATH to installed @earendil-works/pi-coding-agent directory');
const { createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager, getAgentDir } = await import(pathToFileURL(resolve(sdk,'dist/index.js')).href);
const loader = new DefaultResourceLoader({
  cwd: process.cwd(), agentDir: getAgentDir(), noExtensions: true, noSkills: true, noPromptTemplates: true,
  additionalExtensionPaths: [resolve('src/index.ts')],
});
await loader.reload();
const loaded = loader.getExtensions();
assert.deepEqual(loaded.errors, []);
const { session } = await createAgentSession({ resourceLoader: loader, cwd: process.cwd(), sessionManager: SessionManager.inMemory(), settingsManager: SettingsManager.inMemory() });
try {
  const names = session.getActiveToolNames();
  assert(names.includes('local_docs_search')); assert(names.includes('local_docs_read'));
  const search = session.agent.state.tools.find(t => t.name === 'local_docs_search');
  const result = await search.execute('smoke-search', { query: 'Path.walk', name: 'python', version: '3.12.3', limit: 1 }, new AbortController().signal);
  const data = JSON.parse(result.content[0].text);
  assert.equal(data.results.length, 1); assert.match(data.results[0].title, /Path.walk/);
  const read = session.agent.state.tools.find(t => t.name === 'local_docs_read');
  const section = await read.execute('smoke-read', { id: data.results[0].id, length: 500 }, new AbortController().signal);
  const body = JSON.parse(section.content[0].text);
  assert.equal(body.version, '3.12.3'); assert(body.text.length <= 500); assert(body.next_offset !== null);
  assert.match(body.text, /top_down/);
  await assert.rejects(read.execute('smoke-error', { id: 'not-installed' }, new AbortController().signal), /Unknown\/stale/);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(search.execute('smoke-abort', { query: 'Path.walk' }, aborted.signal), /abort/i);
  console.log(JSON.stringify({ piLoaded: true, tools: names.filter(n => n.startsWith('local_docs')), search: data, read: body }, null, 2));
} finally { session.dispose(); }
