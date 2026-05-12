import os
import shlex
import shutil
import subprocess
from pathlib import Path


class EditorManager:
    def __init__(self, root):
        self.root = root

    def _editor_command(self):
        configured = os.environ.get("SIMPYLENS_EDITOR", "code")
        command = (configured or "code").strip()
        if not command:
            command = "code"
        try:
            parts = shlex.split(command, posix=(os.name != "nt"))
        except Exception:
            parts = [command]
        return parts or ["code"]

    def _build_open_arg_candidates(self, command_parts, file_path, line, location_text):
        candidates = []
        seen = set()

        def _add(args):
            key = tuple(str(item) for item in args)
            if key in seen:
                return
            seen.add(key)
            candidates.append(list(key))

        has_placeholders = any(token in part for part in command_parts for token in ("{file}", "{line}", "{location}"))

        if has_placeholders:
            replaced = []
            for part in command_parts:
                replaced.append(part.replace("{file}", str(file_path)).replace("{line}", str(line)).replace("{location}", location_text))
            _add(replaced)
            return candidates

        exe = Path(command_parts[0]).name.lower()

        if exe in {
            "code",
            "code.cmd",
            "code.exe",
            "code-insiders",
            "code-insiders.cmd",
            "code-insiders.exe",
            "codium",
            "codium.cmd",
            "cursor",
            "cursor.cmd",
        }:
            _add([*command_parts, "-g", location_text])

        if "pycharm" in exe or exe in {
            "idea",
            "idea64.exe",
            "webstorm",
            "webstorm64.exe",
            "clion",
            "clion64.exe",
            "rubymine",
            "rubymine64.exe",
            "goland",
            "goland64.exe",
        }:
            _add([*command_parts, "--line", str(line), str(file_path)])

        if exe in {"nvim", "vim", "vi", "nano", "emacs", "emacsclient"}:
            _add([*command_parts, f"+{line}", str(file_path)])

        if exe in {"mate", "subl", "sublime_text"}:
            _add([*command_parts, location_text])

        if exe in {"gedit", "kate", "xed", "pluma", "geany"}:
            _add([*command_parts, f"+{line}", str(file_path)])

        if exe in {"notepad++", "notepad++.exe"}:
            _add([*command_parts, f"-n{line}", str(file_path)])

        # Generic fallbacks for unknown editors/IDEs.
        _add([*command_parts, location_text])
        _add([*command_parts, str(file_path), str(line)])
        _add([*command_parts, "--line", str(line), str(file_path)])
        _add([*command_parts, f"+{line}", str(file_path)])
        _add([*command_parts, str(file_path)])

        return candidates

    def _resolve_editor_command(self, command_parts):
        if not command_parts:
            return ["code"]

        head = command_parts[0]
        has_path_hint = any(sep in head for sep in ("/", "\\")) or Path(head).drive
        if has_path_hint:
            return command_parts

        resolved = shutil.which(head)
        if resolved:
            return [resolved, *command_parts[1:]]

        if os.name == "nt":
            for suffix in (".cmd", ".exe", ".bat"):
                candidate = shutil.which(f"{head}{suffix}")
                if candidate:
                    return [candidate, *command_parts[1:]]

            lowered = head.lower()
            if lowered in {"code", "code-insiders", "code.cmd", "code-insiders.cmd"}:
                local_app_data = os.environ.get("LOCALAPPDATA")
                program_files = os.environ.get("ProgramFiles")
                program_files_x86 = os.environ.get("ProgramFiles(x86)")

                candidates = []
                if local_app_data:
                    candidates.extend(
                        [
                            Path(local_app_data) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                            Path(local_app_data) / "Programs" / "Microsoft VS Code Insiders" / "bin" / "code-insiders.cmd",
                        ]
                    )
                if program_files:
                    candidates.append(Path(program_files) / "Microsoft VS Code" / "bin" / "code.cmd")
                if program_files_x86:
                    candidates.append(Path(program_files_x86) / "Microsoft VS Code" / "bin" / "code.cmd")

                for candidate in candidates:
                    if candidate.exists():
                        return [str(candidate), *command_parts[1:]]

        return command_parts

    def _clipboard_fallback(self, location_text, reason):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(location_text)
            self.root.update_idletasks()
        except Exception:
            pass
        print(f"SimpyLens fallback: copied '{location_text}' to clipboard ({reason}).")

    def open_location(self, file_path, line):
        location_text = f"{file_path}:{line}"
        command_parts = self._editor_command()
        command_parts = self._resolve_editor_command(command_parts)
        candidates = self._build_open_arg_candidates(command_parts, file_path, line, location_text)
        last_exc = None

        for args in candidates:
            try:
                subprocess.Popen(args)
                return True
            except FileNotFoundError as exc:
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                continue

        if isinstance(last_exc, FileNotFoundError):
            self._clipboard_fallback(location_text, "editor not found in PATH")
            return False

        reason = f"all editor launch attempts failed ({last_exc})" if last_exc else "all editor launch attempts failed"
        self._clipboard_fallback(location_text, reason)
        return False
