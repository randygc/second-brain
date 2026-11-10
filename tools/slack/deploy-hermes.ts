/** Stage reviewed code, or activate after the owner's private setup wizard.
 * Run with Bun. All VM access uses the existing stack's hermetic wrappers.
 * No host environment variables configure services. No secret is logged.
 */
import {readFileSync, writeFileSync, readdirSync, mkdirSync, copyFileSync, existsSync, chmodSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const stackRoot = resolve(root, '../hermes-stack-personal');
const mode = process.argv[2];
if (!['stage','activate'].includes(mode)) throw new Error('Usage: bun tools/slack/deploy-hermes.ts stage|activate');
const {orbExec, orbExecWithStdin} = await import(pathToFileURL(resolve(stackRoot,'scripts/lib/orb.ts')).href);
const {stackGet, stackUpsert} = await import(pathToFileURL(resolve(stackRoot,'scripts/lib/stack.ts')).href);
const {generatedGet} = await import(pathToFileURL(resolve(stackRoot,'scripts/lib/generated.ts')).href);
const {parseEnvFile} = await import(pathToFileURL(resolve(stackRoot,'scripts/lib/env.ts')).href);
const vm = `${stackGet('COMPOSE_PROJECT_NAME')}-hermes`;
if (vm !== 'personal-hermes' || stackGet('HERMES_REMOTE_USER') !== 'hermes') throw new Error('Unreviewed stack destination.');
const native = '/opt/hermes-runtime/second-brain-slack';
const home = resolve(stackRoot,'.stack/hermes/.hermes');
const pluginRoot = resolve(root,'integrations/hermes/slack_action_items');
const files:Record<string,string> = {};
for (const name of ['__init__.py','plugin.yaml']) files[name] = readFileSync(resolve(pluginRoot,name),'utf8');
for (const name of readdirSync(resolve(root,'second_brain')).filter((n:string)=>n.endsWith('.py')))
  files[`lib/second_brain/${name}`] = readFileSync(resolve(root,'second_brain',name),'utf8');
const staging = `${native}/staged`;
const install = `import json,sys,pathlib,os,py_compile
os.umask(0o077)
data=json.load(sys.stdin)
root=pathlib.Path('${staging}')
for name,content in data.items():
 p=root/name
 if p.is_absolute() and not p.is_relative_to(root): raise ValueError('Invalid package path')
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(content)
 p.chmod(0o600)
 if p.suffix=='.py': compile(content,str(p),'exec')
print('Reviewed plugin code staged; Slack ingress remains unchanged.')`;
try {
  const revision = await orbExec(vm,"git -C /opt/hermes-agent rev-parse HEAD");
  if (revision !== 'bf0203a794a07aac3ff764972ab9087baa4e4f4e') throw new Error('Hermes revision requires compatibility review.');
  await orbExecWithStdin(vm,`python3 -c ${quote(install)}`,JSON.stringify(files));
  if (mode === 'stage') { console.log('Plugin staged and Python sources compiled in Hermes VM. Not activated.'); process.exit(0); }
  const {parse} = await import(pathToFileURL(resolve(stackRoot,'node_modules/yaml/dist/index.js')).href);
  const route = parse(readFileSync(resolve(stackRoot,'.stack/litellm/config.runtime.yaml'),'utf8'));
  if (route.model_list?.length !== 1 || route.model_list[0].model_name !== 'cliproxy/gpt-6-luna' ||
      route.model_list[0].litellm_params?.api_base !== 'http://cliproxyapi:8317/v1' ||
      route.litellm_settings?.fallbacks?.length !== 0) throw new Error('Subscription-only route drift; review before activation.');
  if (!generatedGet('litellm','HERMES_VIRTUAL_KEY')) throw new Error('Hermes virtual model key missing.');
  const inputsPath = resolve(root,'.local/slack-setup.env');
  const inputs = parseEnvFile(inputsPath);
  for (const [key,pattern] of Object.entries({
    HERMES_SLACK_BOT_TOKEN:/^xoxb-[A-Za-z0-9-]+$/,
    HERMES_SLACK_APP_TOKEN:/^xapp-[A-Za-z0-9-]+$/,
    HERMES_SECOND_BRAIN_WORKSPACE:/^T[A-Z0-9]+$/,
    HERMES_SECOND_BRAIN_CHANNEL:/^[CG][A-Z0-9]+$/,
    HERMES_SECOND_BRAIN_OWNER:/^[UW][A-Z0-9]+$/,
  })) if (!(pattern as RegExp).test(inputs[key] ?? '')) throw new Error(`Missing/invalid ${key}; rerun the private wizard.`);
  const stamp = new Date().toISOString().replace(/[:.]/g,'-');
  const backup = resolve(stackRoot,'_bak',`slack-${stamp}`);
  mkdirSync(backup,{recursive:true,mode:0o700});
  copyFileSync(resolve(stackRoot,'.stack/.env'),resolve(backup,'stack.env'));
  chmodSync(resolve(backup,'stack.env'),0o600);
  for (const key of Object.keys(inputs)) {
    if (!key.startsWith('HERMES_') || /[\r\n]/.test(inputs[key])) throw new Error('Unexpected setup value.');
    stackUpsert(key,inputs[key]);
  }
  const runnerPath = resolve(root,'.local/runner.json');
  const runner = JSON.parse(readFileSync(runnerPath,'utf8'));
  const keyPath = resolve(dirname(runnerPath),runner.api_key_file);
  const bot = stackGet('HERMES_SLACK_BOT_TOKEN');
  const appToken = stackGet('HERMES_SLACK_APP_TOKEN');
  const target = resolve(home,'plugins/second-brain-slack');
  if (existsSync(target)) throw new Error('Existing plugin directory: preserve it and perform a reviewed upgrade; automatic overwrite refused.');
  const config = {
    slack: {workspace_id:stackGet('HERMES_SECOND_BRAIN_WORKSPACE'),channel_id:stackGet('HERMES_SECOND_BRAIN_CHANNEL'),
            owner_id:stackGet('HERMES_SECOND_BRAIN_OWNER'),activation_ts:stackGet('HERMES_SECOND_BRAIN_ACTIVATION_TS')},
    state_dir:`${native}/state`,
    backup_dir:'/home/hermes/.hermes/second-brain-slack-backup',
    linear:{workspace_id:runner.workspace_id,team_id:runner.team_id,backlog_state_id:runner.backlog_state_id,
            key_file:'/home/hermes/.hermes/plugins/second-brain-slack/linear-key'},
    interpreter:{base_url:'http://litellm.personal.orb.local:4000/v1',model:'cliproxy/gpt-6-luna',
                 key_file:'/home/hermes/.hermes/plugins/second-brain-slack/model-key'}
  };
  // Validate actual Slack token workspace, channel privacy/membership and owner membership before publication.
  const verify = `import json,sys,urllib.request,urllib.parse
p=json.load(sys.stdin)
def call(method,params={}):
 req=urllib.request.Request('https://slack.com/api/'+method+'?'+urllib.parse.urlencode(params),headers={'Authorization':'Bearer '+p['token']})
 with urllib.request.urlopen(req,timeout=20) as r: data=json.load(r)
 if not data.get('ok'): raise ValueError('Slack permission verification failed')
 return data
a=call('auth.test'); c=call('conversations.info',{'channel':p['channel']})['channel']
assert a['team_id']==p['workspace'] and c.get('is_private') and c.get('is_member') and not c.get('is_shared') and not c.get('is_archived')
members=[]; cursor=''
for _ in range(100):
 page=call('conversations.members',{'channel':p['channel'],'limit':200,'cursor':cursor})
 members.extend(page['members']); cursor=page.get('response_metadata',{}).get('next_cursor','')
 if not cursor: break
else: raise ValueError('Incomplete channel membership')
assert p['owner'] in members
print('Slack workspace, private channel, bot and owner membership verified.')`;
  try {
    await orbExecWithStdin(vm,`python3 -c ${quote(verify)} 2>/dev/null`,JSON.stringify({token:bot,workspace:config.slack.workspace_id,channel:config.slack.channel_id,owner:config.slack.owner_id}));
  } catch { throw new Error('Slack identity/scope verification failed; no plugin was enabled. Check private inputs and invite the bot.'); }
  // A failed Slack preflight must not move the initial ingestion boundary into the past.
  if (!stackGet('HERMES_SECOND_BRAIN_ACTIVATION_TS')) stackUpsert('HERMES_SECOND_BRAIN_ACTIVATION_TS',(Date.now()/1000).toFixed(6));
  config.slack.activation_ts = stackGet('HERMES_SECOND_BRAIN_ACTIVATION_TS');
  mkdirSync(target,{recursive:true,mode:0o700});
  for (const [name,content] of Object.entries({...files,'runtime.json':JSON.stringify(config,null,2),
        'linear-key':readFileSync(keyPath,'utf8').trim(),'model-key':generatedGet('litellm','HERMES_VIRTUAL_KEY')})) {
    const path=resolve(target,name); mkdirSync(dirname(path),{recursive:true,mode:0o700}); writeFileSync(path,content,{mode:0o600});
  }
  // Systemd environment overrides ordinary agent authorization. Native plugin
  // independently authorizes owner commands; core fallback admits nobody.
  const serviceEnv = [
    `SLACK_BOT_TOKEN=${bot}`,`SLACK_APP_TOKEN=${appToken}`,
    'SLACK_ALLOWED_USERS=__SECOND_BRAIN_PLUGIN_ONLY__','SLACK_ALLOW_ALL_USERS=false',
    'GATEWAY_ALLOWED_USERS=__SECOND_BRAIN_PLUGIN_ONLY__','GATEWAY_ALLOW_ALL_USERS=false',
    'SLACK_DISABLE_DMS=true',`SLACK_ALLOWED_CHANNELS=${config.slack.channel_id}`,
    'SLACK_ALLOW_BOTS=none','SLACK_REACTIONS=false',
  ].join('\n')+'\n';
  writeFileSync(resolve(home,'second-brain-slack.service.env'),serviceEnv,{mode:0o600});
  // Explicit CLI enablement admits pinned plugin dependencies through Hermes PM.
  try {
    await orbExecWithStdin(vm,'/home/hermes/.local/bin/hermes plugins enable second-brain-slack 2>&1', 'y\ny\n');
  } catch { throw new Error('Hermes plugin enablement failed; credentials retained privately, gateway not restarted.'); }
  const activate = `set -e
sudo install -d -m 755 /etc/systemd/system/hermes-gateway.service.d
printf '%s\\n' '[Service]' 'EnvironmentFile=/home/hermes/.hermes/second-brain-slack.service.env' | sudo tee /etc/systemd/system/hermes-gateway.service.d/second-brain-slack.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart hermes-gateway
systemctl is-active hermes-gateway`;
  await orbExec(vm,activate);
  console.log('Slack plugin enabled. Send help in the private channel; complete the documented live smoke test. Setup values remain private.');
} catch (error) {
  // Do not dump errors from subprocess wrappers; these can contain private stdin.
  console.error(error instanceof Error && !('stdout' in error) ? error.message : 'Hermes deployment failed; inspect sanitized state before retrying.');
  process.exitCode=1;
}
function quote(value:string) {return "'"+value.replaceAll("'","'\\''")+"'";}
