#!/usr/bin/env python3
import asyncio
import signal
import os

fields_cfg = [
        {'name':'', 'cmd':'weather.sh', 'interval':5, 'signal':0},
        {'name':'', 'cmd':'network_status.sh', 'interval':5, 'signal':0},
        {'name':'', 'cmd': 'cpu_status.sh', 'interval':5, 'signal':0},
        {'name':'﬙', 'cmd': "free -h | awk '/^Mem/ { print $3\"/\"$2 }' | sed s/i//g", 'interval':30, 'signal':0},
        {'name':'', 'cmd':'vol_control.sh', 'interval':0, 'signal':signal.SIGRTMIN + 10},
        {'name':'', 'cmd':'time_status.sh', 'interval':10, 'signal':0},
        ]



NOT_AVAILABLE='ERROR N/A'
PID_FILE='/tmp/_dwm_dbar.pid'
class DWMStatusBar:
    def __init__(self, cfg, loop):
        self.fields = cfg
        self.loop = loop
        self._prepare()

    def _prepare(self):
        for f in self.fields:
            if f['interval'] > 0:
                f['longrunning'] = self._make_task(f, True)
            if f['signal'] != 0 or f['interval'] <= 0:
                f['oneoff'] = self._make_task(f, False) 
                if f['signal'] != 0:
                    self.loop.add_signal_handler(f['signal'], lambda w=f['oneoff']: asyncio.create_task(w()))
     
    def _make_task(self, field, long_running):
        async def task():
            while True:
                field['output'] = await self._run(field['cmd'])
                await self._refresh()
                if not long_running:
                    break
                if field['interval'] > 0:
                    await asyncio.sleep(field['interval'])
        return task

    async def _run(self, cmd):
        pp = asyncio.subprocess.PIPE
        proc = await asyncio.create_subprocess_shell(cmd, stdout=pp, stderr=pp)
        out, err = await proc.communicate()
        if proc.returncode == 0:
            return out.decode()
        else:
            print(f'error: {err} \nreturn: {proc.returncode}')
            return NOT_AVAILABLE 

    async def _refresh(self):
        res = '  '.join([o.get('output', NOT_AVAILABLE).strip() for o in self.fields])
        cmd = f'xsetroot -name "{res}"'
        await self._run(cmd)

    async def main(self):
        tasks = []
        for f in self.fields:
            if f.get('longrunning'):
                tasks.append(asyncio.create_task(f['longrunning']()))
            elif f.get('oneoff'):
                tasks.append(asyncio.create_task(f['oneoff']()))

        await asyncio.gather(*tasks)
        # Just in case there is no long running task, we still need to
        # stay around, because we may receive signals from users
        while True:
            await asyncio.sleep(1)


if __name__ == '__main__':
    try: os.remove(PID_FILE) 
    except: pass

    pid = os.getpid()
    with open(PID_FILE, 'w') as f:
        f.write(str(pid))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bar = DWMStatusBar(fields_cfg, loop)
    loop.run_until_complete(bar.main())
    