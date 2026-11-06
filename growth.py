"""Discussion-first local account workspace. No publishing or external writes."""
import datetime as dt
import json
import os
import threading
import uuid
import growth_cycle
import subprocess
import sys
from zoneinfo import ZoneInfo

LOCK = threading.RLock()
SYNC_LOCK = threading.Lock()

def today():
    return dt.datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()

def initial():
    return {'version': 0, 'goal': {'target': 1000, 'deadline': '', 'confirmed': False},
            'snapshots': [],
            'metrics': [], 'plans': [], 'messages': [], 'context': ''}

def read(base):
    path = os.path.join(base, 'data', 'growth_workspace.json')
    if not os.path.exists(path):
        return initial()
    with open(path) as f:
        return json.load(f)

def save(base, data):
    path = os.path.join(base, 'data', 'growth_workspace.json')
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def date(value):
    return dt.date.fromisoformat(str(value)).isoformat()

def number(value, optional=False):
    if value in ('', None) and optional:
        return None
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError('数据必须是非负整数；未知请留空')
    return int(value)

def legacy(base):
    try:
        with open(os.path.join(base, 'data', 'xhs_jocelyn_snapshot.json')) as f:
            snap = json.load(f)
    except FileNotFoundError:
        snap = {}
    result = {'date': snap.get('crawled_at'), 'notes': snap.get('notes', [])}
    def optional(name, default):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            return default
        with open(path) as f:
            return json.load(f)
    wuku = optional('static/wuku-data.json', {})
    result['analytics'] = wuku.get('jy_analytics', {}).get('rows', [])
    result['synced_at'] = wuku.get('fetched_at', '')
    drafts = optional('data/wuku_drafts.json', {})
    result['drafts'] = [{'key': k, 'title': v.get('draft', {}).get('title', ''), 'body': v.get('draft', {}).get('body', '')} for k,v in drafts.items() if isinstance(v, dict)]
    result['archive'] = optional('data/wuku_archive.json', [])
    return result

def handle(handler, method, path, base, llm, config):
    if not path.startswith('/api/growth'):
        return False
    try:
        if method == 'GET' and path == '/api/growth':
            with LOCK:
                data = read(base)
            data['today'] = today()
            data['legacy'] = legacy(base)
            data['cycle'] = growth_cycle.view(base, data)
            handler._send_json(data)
            return True
        body = handler._read_json()
        if method != 'POST':
            raise ValueError('不支持的操作')
        if path == '/api/growth/sync':
            if not SYNC_LOCK.acquire(blocking=False):
                handler._send_json({'error':'五库正在同步，请稍后刷新'}, 409)
                return True
            try:
                result = subprocess.run([sys.executable, os.path.join(base, 'tools', 'wuku_sync.py')], capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                handler._send_json({'error':'同步超时，旧快照保留，请稍后重试'}, 503)
                return True
            finally:
                SYNC_LOCK.release()
            if result.returncode:
                handler._send_json({'error':'飞书同步失败，旧快照保留。请检查本机 lark-cli 登录与表访问权限。'}, 503)
            else:
                handler._send_json({'ok': True})
            return True
        if path == '/api/growth/assist':
            with LOCK:
                current = read(base)
            prompt = growth_cycle.assist_prompt(base, current, body)
            reply, error = llm(prompt, config())
            if error or not reply:
                handler._send_json({'error': 'AI 暂时不可用。输入已保留，可复制任务包到 Codex 执行。'}, 503)
            else:
                handler._send_json({'text': reply[:12000]})
            return True
        if path == '/api/growth/discuss':
            message = str(body.get('message', '')).strip()[:4000]
            if not message:
                raise ValueError('先说说你的想法')
            with LOCK:
                data = read(base)
                data['context'] = message
                data['messages'].append({'role': 'user', 'text': message})
                data['version'] += 1
                save(base, data)
            prompt = '''你是 Jocelyn 的账号创作搭档。仅讨论，不代用户决定排期。先回应她的想法，再给一个可行的小建议，最多追问一个关键问题。最多180字，不列多选项、不羞辱、不施压、不承诺涨粉。不固定每天发、不默认21点、不新增平台；能量优先，只做5分钟可启动动作。时间预算未知就先问。用户明确不想聊排期时尊重。目标1000仅是历史愿望，截止日期未定。数据过期需说明，不从赞藏推算涨粉；具体经历不编造。任何讨论均不代表排期已确认。当前日期：''' + today() + '\n真实工作区数据：' + json.dumps(data, ensure_ascii=False)[-18000:]
            reply, error = llm(prompt, config())
            with LOCK:
                latest = read(base)
                latest['messages'].append({'role': 'assistant', 'text': reply[:3000] if reply and not error else '想法已保存。AI 暂时未连接，可以继续记录；等你准备好，我们再一起确认时间和下一步。', 'unavailable': bool(error)})
                latest['version'] += 1
                save(base, latest)
            handler._send_json({'ok': True, 'ai_available': not bool(error)})
            return True
        with LOCK:
            data = read(base)
            if body.get('version') != data['version']:
                handler._send_json({'error': '页面已更新，请刷新后重试，避免覆盖新数据'}, 409)
                return True
            if path == '/api/growth/snapshot':
                day = date(body.get('date'))
                if day > today():
                    raise ValueError('数据日期不能在未来')
                row = {'date': day, 'followers': number(body.get('followers')), 'likes_collects': number(body.get('likes_collects'), True), 'source': '手动录入 · 创作者中心'}
                data['snapshots'] = [s for s in data['snapshots'] if s['date'] != day] + [row]
                data['snapshots'].sort(key=lambda x: x['date'])
            elif path == '/api/growth/goal':
                target = number(body.get('target'))
                if not target:
                    raise ValueError('目标粉丝需大于0')
                deadline = date(body['deadline']) if body.get('deadline') else ''
                if deadline and deadline < today():
                    raise ValueError('目标日期不能在过去')
                data['goal'] = {'target': target, 'deadline': deadline, 'confirmed': True}
            elif path == '/api/growth/metric':
                title = str(body.get('title', '')).strip()[:200]
                day = date(body.get('date'))
                window = body.get('window')
                if not title or day > today() or window not in ('24h', '7d', '累计'):
                    raise ValueError('请核对笔记标题、观察日期与口径')
                row = {'title': title, 'date': day, 'window': window, 'source': '创作者中心手动录入'}
                for k in ('views', 'likes', 'collects', 'comments', 'followers', 'profile_visits'):
                    row[k] = number(body.get(k), True)
                if all(row[k] is None for k in ('views', 'likes', 'collects', 'comments', 'followers', 'profile_visits')):
                    raise ValueError('至少录入一项指标，未知项留空')
                data['metrics'] = [x for x in data['metrics'] if (x['title'], x['date'], x['window']) != (title, day, window)] + [row]
            elif path == '/api/growth/plan':
                title = str(body.get('title', '')).strip()[:200]
                minutes = number(body.get('minutes'))
                day = date(body.get('date'))
                if not title or not 1 <= minutes <= 480 or day < today():
                    raise ValueError('请填写内容、未来或今日日期，以及1–480分钟预算')
                context = str(body.get('context', '')).strip()[:2000]
                if not context:
                    raise ValueError('先记录你的想法与可用时间，再保存待讨论安排')
                plan = {'id': uuid.uuid4().hex[:12], 'title': title, 'date': day, 'minutes': minutes, 'context': context, 'step': str(body.get('step', '')).strip()[:160] or '打开素材，只挑出一段最想讲的内容', 'status': 'proposed'}
                data['plans'].append(plan)
            elif path == '/api/growth/status':
                plan = next((p for p in data['plans'] if p['id'] == body.get('id')), None)
                status = body.get('status')
                allowed = {'proposed': ('confirmed', 'cancelled'), 'confirmed': ('done', 'proposed', 'cancelled'), 'done': ('confirmed',), 'cancelled': ('proposed',)}
                if not plan or status not in allowed[plan['status']]:
                    raise ValueError('排期状态已变化，请刷新')
                if status == 'confirmed':
                    if plan['date'] < today():
                        raise ValueError('日期已过，请新建适合当前时间的安排')
                    if any(p['id'] != plan['id'] and p['date'] == plan['date'] and p['status'] in ('confirmed', 'done') for p in data['plans']):
                        raise ValueError('这天已有一件事，请先撤回原安排')
                plan['status'] = status
            elif growth_cycle.mutate(path, body, data, base, today()):
                pass
            else:
                raise ValueError('未知操作')
            data['version'] += 1
            save(base, data)
        handler._send_json({'ok': True})
    except (ValueError, TypeError) as e:
        handler._send_json({'error': str(e)}, 400)
    except Exception:
        handler._send_json({'error': '读取或保存失败，原数据未被替换。请检查本地服务日志。'}, 500)
    return True
