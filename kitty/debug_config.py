#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import socket
import sys
import termios
import time
from contextlib import suppress
from functools import partial
from pprint import pformat
from typing import IO, Callable, Dict, Iterator, Optional, Sequence, Set, TypeVar

from kittens.tui.operations import colored, styled

from .child import cmdline_of_pid
from .cli import version
from .constants import extensions_dir, is_macos, is_wayland, kitty_base_dir, kitty_exe, shell_path
from .fast_data_types import Color, SingleKey, num_users, wayland_compositor_pid
from .options.types import Options as KittyOpts
from .options.types import defaults
from .options.utils import KeyboardMode, KeyDefinition
from .rgb import color_as_sharp
from .types import MouseEvent, Shortcut, mod_to_names

AnyEvent = TypeVar('AnyEvent', MouseEvent, Shortcut)
Print = Callable[..., None]
ShortcutMap = Dict[Shortcut, str]


def green(x: str) -> str:
    return colored(x, 'green')


def yellow(x: str) -> str:
    return colored(x, 'yellow')


def title(x: str) -> str:
    return colored(x, 'blue', intense=True)


def print_event(ev: str, defn: str, print: Print) -> None:
    print(f'\t{ev} →  {defn}')


def print_mapping_changes(defns: Dict[str, str], changes: Set[str], text: str, print: Print) -> None:
    if changes:
        print(title(text))
        for k in sorted(changes):
            print_event(k, defns[k], print)


def compare_maps(
    final: Dict[AnyEvent, str], final_kitty_mod: int, initial: Dict[AnyEvent, str], initial_kitty_mod: int, print: Print, mode_name: str = ''
) -> None:
    ei = {k.human_repr(initial_kitty_mod): v for k, v in initial.items()}
    ef = {k.human_repr(final_kitty_mod): v for k, v in final.items()}
    added = set(ef) - set(ei)
    removed = set(ei) - set(ef)
    changed = {k for k in set(ef) & set(ei) if ef[k] != ei[k]}
    which = 'shortcuts' if isinstance(next(iter(initial or final)), Shortcut) else 'mouse actions'
    if mode_name and (added or removed or changed):
        print(f'{title("Changes in keyboard mode: " + mode_name)}')
    print_mapping_changes(ef, added, f'Added {which}:', print)
    print_mapping_changes(ei, removed, f'Removed {which}:', print)
    print_mapping_changes(ef, changed, f'Changed {which}:', print)



def compare_opts(opts: KittyOpts, print: Print) -> None:
    from .config import load_config
    print()
    print('Config options different from defaults:')
    default_opts = load_config()
    ignored = ('keymap', 'sequence_map', 'mousemap', 'map', 'mouse_map')
    changed_opts = [
        f for f in sorted(defaults._fields)
        if f not in ignored and getattr(opts, f) != getattr(defaults, f)
    ]
    field_len = max(map(len, changed_opts)) if changed_opts else 20
    fmt = f'{{:{field_len:d}s}}'
    colors = []
    for f in changed_opts:
        val = getattr(opts, f)
        if isinstance(val, dict):
            print(title(f'{f}:'))
            if f == 'symbol_map':
                for k in sorted(val):
                    print(f'\tU+{k[0]:04x} - U+{k[1]:04x} → {val[k]}')
            elif f == 'modify_font':
                for k in sorted(val):
                    print('   ', val[k])
            else:
                print(pformat(val))
        else:
            val = getattr(opts, f)
            if isinstance(val, Color):
                colors.append(fmt.format(f) + ' ' + color_as_sharp(val) + ' ' + styled('  ', bg=val))
            else:
                if f == 'kitty_mod':
                    print(fmt.format(f), '+'.join(mod_to_names(getattr(opts, f))))
                else:
                    print(fmt.format(f), str(getattr(opts, f)))

    compare_maps(opts.mousemap, opts.kitty_mod, default_opts.mousemap, default_opts.kitty_mod, print)
    def as_sc(k: SingleKey, v: KeyDefinition) -> Shortcut:
        if v.is_sequence:
            return Shortcut((v.trigger,) + v.rest)
        return Shortcut((k,))

    def as_str(defns: Sequence[KeyDefinition]) -> str:
        seen = set()
        uniq = []
        for d in reversed(defns):
            key = d.unique_identity_within_keymap
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        return ', '.join(d.human_repr() for d in uniq)

    for kmn, initial_ in default_opts.keyboard_modes.items():
        initial = {as_sc(k, v[0]): as_str(v) for k, v in initial_.keymap.items()}
        final_ = opts.keyboard_modes.get(kmn, KeyboardMode(kmn))
        final = {as_sc(k, v[0]): as_str(v) for k, v in final_.keymap.items()}
        compare_maps(final, opts.kitty_mod, initial, default_opts.kitty_mod, print, mode_name=kmn)
    new_keyboard_modes = set(opts.keyboard_modes) - set(default_opts.keyboard_modes)
    for kmn in new_keyboard_modes:
        initial_ = KeyboardMode(kmn)
        initial = {as_sc(k, v[0]): as_str(v) for k, v in initial_.keymap.items()}
        final_ = opts.keyboard_modes[kmn]
        final = {as_sc(k, v[0]): as_str(v) for k, v in final_.keymap.items()}
        compare_maps(final, opts.kitty_mod, initial, default_opts.kitty_mod, print, mode_name=kmn)
    if colors:
        print(f'{title("Colors")}:', end='\n\t')
        print('\n\t'.join(sorted(colors)))


class IssueData:

    def __init__(self) -> None:
        self.uname = os.uname()
        self.s, self.n, self.r, self.v, self.m = self.uname
        try:
            self.hostname = self.o = socket.gethostname()
        except Exception:
            self.hostname = self.o = 'localhost'
        _time = time.localtime()
        self.formatted_time = self.d = time.strftime('%a %b %d %Y', _time)
        self.formatted_date = self.t = time.strftime('%H:%M:%S', _time)
        try:
            self.tty_name = format_tty_name(os.ctermid())
        except OSError:
            self.tty_name = '(none)'
        self.l = self.tty_name
        self.baud_rate = 0
        if sys.stdin.isatty():
            with suppress(OSError):
                self.baud_rate = termios.tcgetattr(sys.stdin.fileno())[5]
        self.b = str(self.baud_rate)
        try:
            self.num_users = num_users()
        except RuntimeError:
            self.num_users = -1
        self.u = str(self.num_users)
        self.U = self.u + ' user' + ('' if self.num_users == 1 else 's')

    def translate_issue_char(self, char: str) -> str:
        try:
            return str(getattr(self, char)) if len(char) == 1 else char
        except AttributeError:
            return char

    def parse_issue_file(self, issue_file: IO[str]) -> Iterator[str]:
        last_char: Optional[str] = None
        while True:
            this_char = issue_file.read(1)
            if not this_char:
                break
            if last_char == '\\':
                yield self.translate_issue_char(this_char)
            elif last_char is not None:
                yield last_char
            # `\\\a` should not match the last two slashes,
            # so make it look like it was `\?\a` where `?`
            # is some character other than `\`.
            last_char = None if last_char == '\\' else this_char
        if last_char is not None:
            yield last_char


def format_tty_name(raw: str) -> str:
    return re.sub(r'^/dev/([^/]+)/([^/]+)$', r'\1\2', raw)


def compositor_name() -> str:
    ans = 'X11'
    if is_wayland():
        ans = 'Wayland'
        with suppress(Exception):
            pid = wayland_compositor_pid()
            if pid > -1:
                cmdline = cmdline_of_pid(pid)
                exe = cmdline[0]
                with suppress(Exception):
                    import subprocess
                    if exe.lower() == 'hyprland':
                        raw = subprocess.check_output(['hyprctl', 'version']).decode().strip()
                        m = re.search(r'^Tag:\s*(\S+)', raw, flags=re.M)
                        if m is not None:
                            exe = f'{exe} {m.group(1)}'
                        else:
                            exe = raw.splitlines()[0]
                    exe = subprocess.check_output([exe, '--version']).decode().strip().splitlines()[0]
                ans += f' ({exe})'
    return ans


def debug_config(opts: KittyOpts) -> str:
    from io import StringIO
    out = StringIO()
    p = partial(print, file=out)
    p(version(add_rev=True))
    p(' '.join(os.uname()))
    if is_macos:
        import subprocess
        p(' '.join(subprocess.check_output(['sw_vers']).decode('utf-8').splitlines()).strip())
    if os.path.exists('/etc/issue'):
        try:
            idata = IssueData()
        except Exception:
            pass
        else:
            with open('/etc/issue', encoding='utf-8', errors='replace') as f:
                try:
                    datums = idata.parse_issue_file(f)
                except Exception:
                    pass
                else:
                    p(end=''.join(datums))
    if os.path.exists('/etc/lsb-release'):
        with open('/etc/lsb-release', encoding='utf-8', errors='replace') as f:
            p(f.read().strip())
    if not is_macos:
        p('Running under:', green(compositor_name()))
    p(green('Frozen:'), 'True' if getattr(sys, 'frozen', False) else 'False')
    p(green('Paths:'))
    p(yellow('  kitty:'), os.path.realpath(kitty_exe()))
    p(yellow('  base dir:'), kitty_base_dir)
    p(yellow('  extensions dir:'), extensions_dir)
    p(yellow('  system shell:'), shell_path)
    if opts.config_paths:
        p(green('Loaded config files:'))
        p(' ', '\n  '.join(opts.config_paths))
    if opts.config_overrides:
        p(green('Loaded config overrides:'))
        p(' ', '\n  '.join(opts.config_overrides))
    compare_opts(opts, p)
    p()
    p(green('Important environment variables seen by the kitty process:'))

    def penv(k: str) -> None:
        v = os.environ.get(k)
        if v is not None:
            p('\t' + k.ljust(35), styled(v, dim=True))

    for k in (
        'PATH LANG KITTY_CONFIG_DIRECTORY KITTY_CACHE_DIRECTORY VISUAL EDITOR SHELL'
        ' GLFW_IM_MODULE KITTY_WAYLAND_DETECT_MODIFIERS DISPLAY WAYLAND_DISPLAY USER XCURSOR_SIZE'
    ).split():
        penv(k)
    for k in os.environ:
        if k.startswith('LC_') or k.startswith('XDG_'):
            penv(k)
    return out.getvalue()
