"""
FileScanner - 文件扫描器
========================

高效的文件列表获取，优先使用 git ls-files。

策略：
1. 优先使用 git ls-files（最快，读取 git 索引）
2. 回退到 ripgrep --files（次快）
3. 最后使用 Python os.walk（最慢）

用法:
    scanner = FileScanner("/path/to/project")
    result = scanner.scan()
    print(f"找到 {len(result.files)} 个文件")
"""

import os
import subprocess
import asyncio
import time
from pathlib import Path
from typing import List, Optional, Set
from dataclasses import dataclass


@dataclass
class ScanResult:
    """扫描结果"""
    files: List[str]           # 文件列表
    directories: List[str]     # 目录列表
    total: int                 # 总文件数
    duration_ms: int           # 扫描耗时
    method: str                # 使用的方法 (git, ripgrep, walk)


class FileScanner:
    """
    文件扫描器。

    使用最快的可用方法获取文件列表。

    示例:
        scanner = FileScanner("/project")

        # 同步扫描
        result = scanner.scan()
        for f in result.files:
            print(f)

        # 异步扫描
        result = await scanner.scan_async()
    """

    # 要排除的版本控制目录
    VCS_DIRS = {'.git', '.svn', '.hg', '.bzr', '.jj', '.sl'}

    def __init__(self, root_path: str):
        """
        初始化扫描器。

        Args:
            root_path: 根目录路径
        """
        self.root_path = Path(root_path).resolve()
        self._git_root: Optional[Path] = None
        self._rg_available: Optional[bool] = None

    def scan(
        self,
        use_git: bool = True,
        respect_gitignore: bool = True,
        include_hidden: bool = False,
        include_dirs: bool = True,
    ) -> ScanResult:
        """
        扫描文件。

        Args:
            use_git: 是否优先使用 git ls-files
            respect_gitignore: 是否遵循 .gitignore
            include_hidden: 是否包含隐藏文件
            include_dirs: 是否包含目录列表

        Returns:
            ScanResult 对象
        """
        start_ms = int(time.time() * 1000)

        files: List[str] = []
        method = "walk"

        # 策略 1: git ls-files
        if use_git and self._is_git_repo():
            git_files = self._scan_with_git(respect_gitignore)
            if git_files is not None:
                files = git_files
                method = "git"

        # 策略 2: ripgrep --files
        if not files and self._check_rg_available():
            rg_files = self._scan_with_ripgrep(respect_gitignore, include_hidden)
            if rg_files:
                files = rg_files
                method = "ripgrep"

        # 策略 3: Python os.walk
        if not files:
            files = self._scan_with_walk(include_hidden)

        # 获取目录列表
        directories = []
        if include_dirs:
            directories = self._extract_directories(files)

        end_ms = int(time.time() * 1000)

        return ScanResult(
            files=files,
            directories=directories,
            total=len(files),
            duration_ms=end_ms - start_ms,
            method=method
        )

    async def scan_async(
        self,
        use_git: bool = True,
        respect_gitignore: bool = True,
        include_hidden: bool = False,
        include_dirs: bool = True,
    ) -> ScanResult:
        """
        异步扫描文件。

        使用 asyncio.subprocess 避免阻塞事件循环。
        """
        start_ms = int(time.time() * 1000)

        files: List[str] = []
        method = "walk"

        # 策略 1: git ls-files
        if use_git and self._is_git_repo():
            git_files = await self._scan_with_git_async(respect_gitignore)
            if git_files is not None:
                files = git_files
                method = "git"

        # 策略 2: ripgrep --files
        if not files and self._check_rg_available():
            rg_files = await self._scan_with_ripgrep_async(respect_gitignore, include_hidden)
            if rg_files:
                files = rg_files
                method = "ripgrep"

        # 策略 3: Python os.walk
        if not files:
            files = await self._scan_with_walk_async(include_hidden)

        directories = []
        if include_dirs:
            directories = self._extract_directories(files)

        end_ms = int(time.time() * 1000)

        return ScanResult(
            files=files,
            directories=directories,
            total=len(files),
            duration_ms=end_ms - start_ms,
            method=method
        )

    # ==================== Git ls-files ====================

    def _is_git_repo(self) -> bool:
        """检查是否是 git 仓库"""
        if self._git_root is not None:
            return True

        # 向上查找 .git
        current = self.root_path
        while current != current.parent:
            git_dir = current / '.git'
            if git_dir.exists():
                self._git_root = current
                return True
            current = current.parent

        return False

    def _scan_with_git(self, respect_gitignore: bool) -> Optional[List[str]]:
        """使用 git ls-files 扫描"""
        if not self._git_root:
            return None

        try:
            # 获取 tracked 文件
            result = subprocess.run(
                ['git', '-c', 'core.quotepath=false', 'ls-files', '--recurse-submodules'],
                cwd=self._git_root,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None

            files = result.stdout.strip().split('\n')
            files = [f for f in files if f]

            # 规范化路径（相对于搜索根目录）
            if self._git_root != self.root_path:
                prefix = self.root_path.relative_to(self._git_root)
                files = [f for f in files if f.startswith(str(prefix) + '/') or f.startswith(str(prefix))]
                files = [f[len(str(prefix)) + 1:] if f.startswith(str(prefix) + '/') else f for f in files]

            return files

        except (subprocess.SubprocessError, Exception):
            return None

    async def _scan_with_git_async(self, respect_gitignore: bool) -> Optional[List[str]]:
        """异步使用 git ls-files"""
        if not self._git_root:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                'git', '-c', 'core.quotepath=false', 'ls-files', '--recurse-submodules',
                cwd=self._git_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                return None

            files = stdout.decode().strip().split('\n')
            files = [f for f in files if f]

            # 规范化路径
            if self._git_root != self.root_path:
                prefix = self.root_path.relative_to(self._git_root)
                files = [f for f in files if f.startswith(str(prefix) + '/')]
                files = [f[len(str(prefix)) + 1:] for f in files]

            return files

        except (asyncio.TimeoutError, Exception):
            return None

    # ==================== Ripgrep --files ====================

    def _check_rg_available(self) -> bool:
        """检查 ripgrep 是否可用"""
        if self._rg_available is not None:
            return self._rg_available

        try:
            result = subprocess.run(
                ['rg', '--version'],
                capture_output=True,
                timeout=5
            )
            self._rg_available = result.returncode == 0
        except Exception:
            self._rg_available = False

        return self._rg_available

    def _scan_with_ripgrep(
        self,
        respect_gitignore: bool,
        include_hidden: bool
    ) -> Optional[List[str]]:
        """使用 ripgrep --files 扫描"""
        args = ['rg', '--files', '--follow']

        if include_hidden:
            args.append('--hidden')

        if not respect_gitignore:
            args.append('--no-ignore-vcs')

        # 排除版本控制目录
        for vcs_dir in self.VCS_DIRS:
            args.extend(['--glob', f'!{vcs_dir}'])

        try:
            result = subprocess.run(
                args,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode in (0, 1):
                files = result.stdout.strip().split('\n')
                return [f for f in files if f]

            return None

        except Exception:
            return None

    async def _scan_with_ripgrep_async(
        self,
        respect_gitignore: bool,
        include_hidden: bool
    ) -> Optional[List[str]]:
        """异步使用 ripgrep --files"""
        args = ['rg', '--files', '--follow']

        if include_hidden:
            args.append('--hidden')

        if not respect_gitignore:
            args.append('--no-ignore-vcs')

        for vcs_dir in self.VCS_DIRS:
            args.extend(['--glob', f'!{vcs_dir}'])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.root_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode in (0, 1):
                files = stdout.decode().strip().split('\n')
                return [f for f in files if f]

            return None

        except Exception:
            return None

    # ==================== Python os.walk ====================

    def _scan_with_walk(self, include_hidden: bool) -> List[str]:
        """使用 Python os.walk 扫描"""
        files = []

        for root, dirs, filenames in os.walk(self.root_path):
            # 排除版本控制目录
            dirs[:] = [d for d in dirs if d not in self.VCS_DIRS]

            # 排除隐藏目录
            if not include_hidden:
                dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in filenames:
                # 排除隐藏文件
                if not include_hidden and filename.startswith('.'):
                    continue

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self.root_path)
                files.append(rel_path)

        return files

    async def _scan_with_walk_async(self, include_hidden: bool) -> List[str]:
        """异步使用 Python os.walk"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._scan_with_walk(include_hidden)
        )

    # ==================== 工具方法 ====================

    def _extract_directories(self, files: List[str]) -> List[str]:
        """从文件列表中提取目录"""
        dirs: Set[str] = set()

        for filepath in files:
            dir_path = os.path.dirname(filepath)
            while dir_path:
                dirs.add(dir_path)
                dir_path = os.path.dirname(dir_path)

        return sorted(dirs)


# ==================== 便捷函数 ====================

def list_files(root_path: str, use_git: bool = True) -> List[str]:
    """
    列出目录中的所有文件。

    Args:
        root_path: 根目录路径
        use_git: 是否优先使用 git ls-files

    Returns:
        文件路径列表
    """
    scanner = FileScanner(root_path)
    result = scanner.scan(use_git=use_git)
    return result.files
