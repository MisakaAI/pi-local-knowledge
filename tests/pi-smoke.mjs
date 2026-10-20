// Loads the extension in a real Pi agent session and calls its tools through Pi's wrappers.
// Uses a temporary store built from tests/fixtures unless PI_KNOWLEDGE_HOME is already set.
// Pi is resolved from PI_SDK_PATH (installed package directory) or from node_modules.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { pathToFileURL } from 'node:url';
import { join, resolve } from 'node:path';

const sdk = process.env.PI_SDK_PATH;
const { createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager, getAgentDir } =
  await import(sdk ? pathToFileURL(resolve(sdk, 'dist/index.js')).href : '@earendil-works/pi-coding-agent');

const python = process.env.PI_KNOWLEDGE_PYTHON || 'python3';
const temp = process.env.PI_KNOWLEDGE_HOME ? undefined : mkdtempSync(join(tmpdir(), 'pi-docs-smoke-'));
if (temp) {
  process.env.PI_KNOWLEDGE_HOME = temp;
  process.env.PI_KNOWLEDGE_CONFIG = resolve('config/sources.example.json');
  execFileSync(python, ['backend/knowledge.py', 'install', '--source', 'project-manual'], { stdio: 'pipe' });
}
const fixture = !!temp;

const loader = new DefaultResourceLoader({
  cwd: process.cwd(), agentDir: getAgentDir(), noExtensions: true, noSkills: true, noPromptTemplates: true,
  additionalExtensionPaths: [resolve('src/index.ts')],
});
await loader.reload();
assert.deepEqual(loader.getExtensions().errors, []);
const { session } = await createAgentSession({ resourceLoader: loader, cwd: process.cwd(), sessionManager: SessionManager.inMemory(), settingsManager: SettingsManager.inMemory() });
try {
  await session.bindExtensions?.({});
  const names = session.getActiveToolNames();
  assert(names.includes('local_docs_search')); assert(names.includes('local_docs_read'));
  const tool = name => session.agent.state.tools.find(t => t.name === name);
  const [query, name, version, title, body] = fixture
    ? ['widget.run', 'example', '1.0.0', /widget\.run/, /widget\.run\(42\)/]
    : ['Path.walk', 'python', '3.12.3', /Path\.walk/, /top_down/];
  const search = tool('local_docs_search');
  const result = await search.execute('smoke-search', { query, name, version, limit: 1 }, new AbortController().signal);
  const data = JSON.parse(result.content[0].text);
  assert.equal(data.results.length, 1); assert.match(data.results[0].title, title);
  assert.deepEqual(data.searched, [`${name}@${version}`]);
  const read = tool('local_docs_read');
  const section = await read.execute('smoke-read', { id: data.results[0].id, length: 500 }, new AbortController().signal);
  const part = JSON.parse(section.content[0].text);
  assert.equal(part.version, version); assert(part.text.length <= 500); assert.match(part.text, body);
  await assert.rejects(read.execute('smoke-error', { id: 'not-installed' }, new AbortController().signal), /Unknown\/stale/);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(search.execute('smoke-abort', { query }, aborted.signal), /abort/i);
  const description = tool('local_docs_search').description;
  console.log(JSON.stringify({ piLoaded: true, tools: names.filter(n => n.startsWith('local_docs')), catalogInDescription: description.includes(`${name}@${version}`), search: data, read: part }, null, 2));
} finally {
  session.dispose();
  if (temp) rmSync(temp, { recursive: true, force: true });
}
