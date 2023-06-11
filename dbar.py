#!/usr/bin/env python3
import asyncio
import signal
import time
import os, sys
import argparse
import subprocess
import logging

logger = logging.getLogger('Mydwmbar')

NOT_AVAILABLE = "ERROR N/A"
PID_FILE = "/tmp/_dwm_dbar.pid"

level = logging.INFO

loop = asyncio.new_event_loop()


def human_format(num, suffix="B"):
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}{suffix}" if unit else f"{num:.0f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


async def async_run(cmd):
    pp = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_shell(cmd, stdout=pp, stderr=pp)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f'Command: "{cmd}" failed, {err}')
    return out.decode(), proc.returncode


class Task:
    def __init__(
        self,
        icon=[],
        interval=0,
        signal=0,
        width=0,
        fgcolor="",
        bgcolor="",
        fgcolor2="",
        bgcolor2="",
    ):
        self.interval = interval
        self.signal = signal
        self.sig_setup = signal == 0
        self.width = width
        self.dirty = False
        self.icon = icon
        self.raw_output = ""
        self.output = ""
        self.fgcolor = fgcolor
        self.fgcolor2 = fgcolor2
        self.bgcolor = bgcolor
        self.bgcolor2 = bgcolor2
        self.cb = None

    def _format(self, out, width):
        return out.ljust(width) if width else out

    def _beautify(self, out):
        head = ""
        if self.icon:
            fg = f"^c{self.fgcolor}^" if self.fgcolor else ""
            bg = f"^b{self.bgcolor}^" if self.bgcolor else ""
            head = self.icon[0]
            head = f"{fg}{bg}{head}"

        fg2 = f"^c{self.fgcolor2}^" if self.fgcolor2 else ""
        bg2 = f"^b{self.bgcolor2}^" if self.bgcolor2 else ""
        return f"{head}{fg2}{bg2}{out}^d^"

    def _update(self, out):
        out = self._format(out, self.width)
        if out != self.raw_output:
            self.raw_output = out
            self.dirty = True
            self.output = self._beautify(out)
            if self.cb:
                asyncio.create_task(self.cb())

    def set_async_callback(self, cb):
        self.cb = cb

    def get_output(self):
        b = self.dirty
        self.dirty = False
        return self.output, b

    async def work_meat(self):
        pass

    async def work(self):
        if self.signal != 0 and not self.sig_setup:
            # This can be triggered by signal
            loop.add_signal_handler(
                self.signal, lambda: asyncio.create_task(self.work_meat())
            )
            self.sig_setup = True

        while True:
            await self.work_meat()
            if self.interval != 0:
                await asyncio.sleep(self.interval)
            else:
                break


class MemTask(Task):
    def __init__(self):
        super().__init__(
            interval=30,
            width=11,
            icon=[" ﬙  "],
            fgcolor="#222222",
            bgcolor="#8844ff",
            fgcolor2="#222222",
            bgcolor2="#aa88ff",
        )

    async def work_meat(self):
        mem, _ = await async_run(
            "free -h | awk '/^Mem/ { print $3\"/\"$2 }' | sed s/i//g"
        )
        self._update(" " + mem.strip())


class CPUTask(Task):
    def __init__(self):
        super().__init__(
            interval=3,
            width=12,
            icon=["   "],
            fgcolor="#222222",
            bgcolor="#d6482f",
            fgcolor2="#222222",
            bgcolor2="#e87c68",
        )
        self.prev_busy = 0
        self.prev_total = 0

    async def work_meat(self):
        with open("/proc/stat") as f:
            nums = [int(x) for x in f.readline().strip().split()[1:]]
            idle = nums[3]
            total = sum(nums)
            busy = total - idle
            cpu = f"{(100 * (busy - self.prev_busy) / (total - self.prev_total)):.0f}%"
            self.prev_busy, self.prev_total = busy, total

        thermal, code = await async_run(
            r"sensors | grep 'Package id 0' | sed -r 's/.*Package id 0:  \+([0-9\.]+)°C.*/\1°C/'"
        )
        if code != 0:
            thermal = "N/A"
        self._update(" " + cpu + " " + thermal.strip())


class AudioControlTask(Task):
    def __init__(self):
        super().__init__(
            interval=0,
            signal=signal.SIGRTMIN + 10,
            width=6,
            icon=[" ﱝ", " 奄", " 奔", " 墳", " "],
            fgcolor="#222222",
            bgcolor="#77ff33",
            fgcolor2="#222222",
            bgcolor2="#aaff88",
        )
        self.attempts = 10

    def _format(self, out, width):
        return out.center(width) if width else out

    def _beautify(self, out):
        _ = out
        try:
            v = int(self.raw_output.strip())
            head = ""
            if v == 0:
                head = self.icon[0] + " "
            elif v < 33:
                head = self.icon[1] + " "
            elif v < 66:
                head = self.icon[2] + " "
            elif v < 100:
                head = self.icon[3] + " "
            else:
                head = self.icon[4] + " "
            body = self._format(str(v) + "%", self.width)
            return f"^c{self.fgcolor}^^b{self.bgcolor}^{head} ^c{self.fgcolor2}^^b{self.bgcolor2}^{body}^d^"
        except:
            return NOT_AVAILABLE

    async def work_meat(self):
        code = 1
        while code != 0:
            vol, code = await async_run(
                r"amixer get Master | tail -n1 | sed -r 's/.*\[(.*)%\].*/\1/'"
            )
            if code == 0:
                self.attempts = 10
                self._update(" " + vol.strip())
                break
            if self.attempts > 0:
                self.attempts -= 1
                await asyncio.sleep(1)
            else:
                self._update(" " + NOT_AVAILABLE)
                break


class NetworkTask(Task):
    def __init__(self, name, icon, fgcolor, bgcolor, fgcolor2, bgcolor2):
        super().__init__(
            interval=3,
            signal=0,
            width=22,
            icon=icon,
            fgcolor=fgcolor,
            bgcolor=bgcolor,
            fgcolor2=fgcolor2,
            bgcolor2=bgcolor2,
        )
        self.name = name
        self.available = True
        self.rx = 0
        self.tx = 0
        self.last_read = 0

    def _beautify(self, out):
        if not self.available:
            return ""
        return super()._beautify(out)

    def _format(self, out, width):
        return out.center(width) if width else out

    async def work_meat(self):
        result, status = await async_run(
            f"nmcli device status | grep {self.name} | grep connected"
        )
        if status != 0 and not result:
            self.output = ""
            self.available = False
            self.dirty = False
            return
        self.available = True
        device = result.split()[0]
        with open(f"/sys/class/net/{device}/statistics/rx_bytes") as f:
            rx = int(f.read().strip())
        with open(f"/sys/class/net/{device}/statistics/tx_bytes") as f:
            tx = int(f.read().strip())

        rx_diff, tx_diff = rx - self.rx, tx - self.tx
        self.rx, self.tx = rx, tx
        tm = time.monotonic()
        # first time run, just return
        if self.last_read == 0:
            self.last_read = tm
            return ""

        rx_speed = "" + human_format(rx_diff / (tm - self.last_read)) + "/S"
        tx_speed = "" + human_format(tx_diff / (tm - self.last_read)) + "/S"
        self.last_read = tm
        self._update(" " + rx_speed + " " + tx_speed)


class EthernetTask(NetworkTask):
    def __init__(self):
        super().__init__(
            "ethernet",
            ["   "],
            fgcolor="#222222",
            bgcolor="#e0c516",
            fgcolor2="#222222",
            bgcolor2="#f2e383",
        )


class WifiTask(NetworkTask):
    def __init__(self):
        super().__init__(
            "wifi",
            [" 直  "],
            fgcolor="#222222",
            bgcolor="#4441f2",
            fgcolor2="#222222",
            bgcolor2="#8886f0",
        )


class DateTask(Task):
    def __init__(self, interval=30, icon=["   "], width=22):
        super().__init__(
            interval=interval,
            icon=icon,
            width=width,
            fgcolor="#222222",
            bgcolor="#4488ff",
            fgcolor2="#222222",
            bgcolor2="#88aaff",
        )

    async def work_meat(self):
        time_info, _ = await async_run('date "+%a %b %d %I:%M%p"')
        self._update(" " + time_info.strip())


class DBar:
    def __init__(self):
        try:
            self.ppid = int(subprocess.check_output("pgrep dwm", shell=True))
        except:
            sys.exit(1)

        self.tasks = [
            WifiTask(),
            EthernetTask(),
            CPUTask(),
            MemTask(),
            AudioControlTask(),
            DateTask(),
        ]
        for t in self.tasks:
            t.set_async_callback(self._update)

    async def _check_dwm(self):
        # monitor dwm process id, if dwm is not running, exit
        while True:
            try:
                os.kill(self.ppid, 0)
            except OSError:
                sys.exit()
            await asyncio.sleep(1)

    async def _update(self):
        status, dirty = self.tasks[0].get_output()
        for t in self.tasks[1:]:
            s, b = t.get_output()
            if s:
                status += " " + s
            dirty = b or dirty
        if dirty:
            status = status + " "
            await async_run(f'xsetroot -name "{status}"')

    async def run(self):
        tasks = [asyncio.create_task(self._check_dwm())]
        # wait 1.5 seconds if dwm is not running, the program will exit
        await asyncio.sleep(1.5)
        for task in self.tasks:
            tasks.append(asyncio.create_task(task.work()))

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="dbar")
    parser.add_argument(
        "--pid",
        dest="pid",
        action="store_true",
        default=False,
        help="If specified, the program will generate a pid file under /tmp",
    )
    parser.add_argument(
            "--logfile",
            dest="logfile",
            default="",
            help="If specified, logs will be output to the file, otherwise just be shown in stdout")

    args = parser.parse_args()
    pid = os.getpid()
    logging.basicConfig(
            filename=args.logfile,
            #format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
            format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
            datefmt='%H:%M:%S',
            level=level
            )

    if args.pid:
        try:
            with open(PID_FILE, "w") as f:
                f.truncate()
                f.write(str(pid))
        except Exception as e:
            logger.error(f"Exception: {e}")

    try:
        asyncio.set_event_loop(loop)
        bar = DBar()
        loop.run_until_complete(bar.run())
    except Exception as e:
        logger.error(f"Main even loop exception: {e}")
