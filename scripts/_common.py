"""数据处理脚本的通用工具"""

import asyncio
from contextlib import contextmanager
from datetime import datetime
import functools
from pathlib import Path
import time
from typing import Any, Callable, Optional, ParamSpec, TypeVar
from git import Repo
from git.exc import GitCommandError
from pytz import timezone
import httpx


class DataRepoManager:
    """管理数据仓库的更新和提交"""

    def __init__(self, local_path: str = "."):
        """
        初始化仓库管理器

        Args:
            local_path: 仓库路径，在 GitHub Actions 中通常是当前目录或指定的 path
        """
        self.local_path = Path(local_path)
        self.repo: Optional[Repo] = None

    def open(self) -> Repo:
        """
        打开已存在的 Git 仓库（由 actions/checkout 检出）

        Returns:
            Repo: GitPython 仓库对象
        """
        if not self.local_path.exists():
            raise RuntimeError(f"仓库路径不存在：{self.local_path}")

        if not (self.local_path / ".git").exists():
            raise RuntimeError(f"路径不是 Git 仓库：{self.local_path}")

        self.repo = Repo(self.local_path)
        print(f"✅ 已打开仓库：{self.local_path}")
        print(f"   当前分支：{self.repo.active_branch.name}")
        print(f"   最新提交：{self.repo.head.commit.hexsha[:8]}")
        return self.repo

    @classmethod
    def from_checkout(cls, path: str = ".") -> "DataRepoManager":
        """
        便捷方法：从 actions/checkout 检出的仓库创建管理器

        Args:
            path: 仓库路径

        Returns:
            已初始化的 DataRepoManager 实例
        """
        manager = cls(path)
        manager.open()
        return manager

    def has_changes(self) -> bool:
        """检查工作区是否有未提交的更改"""
        if not self.repo:
            raise RuntimeError("仓库尚未初始化")

        return (
            self.repo.is_dirty(untracked_files=True)
            or len(self.repo.untracked_files) > 0
        )

    def get_changed_files(self) -> list[str]:
        """获取已更改的文件列表"""
        if not self.repo:
            raise RuntimeError("仓库尚未初始化")

        changed_files = []

        # 已修改的文件
        changed_files.extend([item.a_path for item in self.repo.index.diff(None)])

        # 已暂存的文件
        changed_files.extend([item.a_path for item in self.repo.index.diff("HEAD")])

        # 未跟踪的文件
        changed_files.extend(self.repo.untracked_files)

        return list(set(changed_files))

    def commit(self, message: str, files: Optional[list[str]] = None) -> bool:
        """
        提交更改

        Args:
            message: 提交信息
            files: 要提交的文件列表，None 表示添加所有更改

        Returns:
            bool: 是否成功提交
        """
        if not self.repo:
            raise RuntimeError("仓库尚未初始化")

        # 记录初始 commit
        initial_commit = self.repo.head.commit

        # 检查是否有更改
        if not self.has_changes():
            print("📭 没有检测到更改，跳过提交")
            return False

        # 显示更改的文件
        changed_files = self.get_changed_files()
        print(f"📝 检测到 {len(changed_files)} 个文件有更改：")
        for file in changed_files[:10]:  # 只显示前 10 个
            print(f"  - {file}")
        if len(changed_files) > 10:
            print(f"  ... 还有 {len(changed_files) - 10} 个文件")

        # 添加文件
        if files:
            self.repo.index.add(files)
        else:
            self.repo.git.add(A=True)  # 相当于 git add -A

        # 提交
        try:
            self.repo.index.commit(message)
            print(f"✅ 提交成功：{message}")
        except GitCommandError as e:
            print(f"❌ 提交失败：{e}")
            return False

        # 检查是否创建了新 commit
        if self.repo.head.commit == initial_commit:
            print("⚠️  没有创建新的 commit（可能所有更改都已提交）")
            return False

        return True

    def push(self, remote: str = "origin", branch: Optional[str] = None) -> bool:
        """
        推送更改到远程仓库

        Args:
            remote: 远程仓库名称，默认 "origin"
            branch: 要推送的分支，None 表示推送当前分支

        Returns:
            bool: 是否成功推送
        """
        if not self.repo:
            raise RuntimeError("仓库尚未初始化")

        try:
            print("⬆️  正在推送到远程仓库...")

            # 获取远程仓库
            origin = self.repo.remotes[remote]

            # 推送
            if branch:
                push_info = origin.push(branch)
            else:
                push_info = origin.push()

            # 检查推送结果
            for info in push_info:
                if info.flags & info.ERROR:
                    print(f"❌ 推送失败：{info.summary}")
                    return False

            print("✅ 推送成功")
            return True

        except GitCommandError as e:
            print(f"❌ 推送失败：{e}")
            return False
        except IndexError:
            print(f"❌ 远程仓库 '{remote}' 不存在")
            return False

    def commit_and_push(self, message: str, files: Optional[list[str]] = None) -> bool:
        """
        提交并推送更改（便捷方法）

        Args:
            message: 提交信息
            files: 要提交的文件列表，None 表示添加所有更改

        Returns:
            bool: 是否成功提交并推送
        """
        # 先提交
        if not self.commit(message, files):
            return False

        # 再推送
        return self.push()

    @contextmanager
    def auto_commit(self, commit_message: str):
        """
        上下文管理器：自动检查并提交更改

        使用示例：
            with manager.auto_commit("更新数据"):
                # 执行数据处理操作
                process_data()
        """
        initial_commit = self.repo.head.commit if self.repo else None

        try:
            yield self
        finally:
            if self.repo and self.repo.head.commit != initial_commit:
                # 在上下文中已经有新 commit 了
                print("检测到已有新提交")
            elif self.has_changes():
                # 有未提交的更改
                self.commit_and_push(commit_message)
            else:
                print("📭 没有检测到更改")


def get_data_path(base_path: Path, *parts: str) -> Path:
    """构建数据文件路径"""
    path = base_path / Path(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_to_github_output(name: str, value: str) -> None:
    """写入输出到 GitHub Actions 的 GITHUB_OUTPUT 文件

    Args:
            name: 输出变量的名称
            value: 输出变量的值
    """
    import os

    github_output = os.getenv("GITHUB_OUTPUT")
    if not github_output:
        print("警告：未找到 GITHUB_OUTPUT 环境变量")
        return

    with open(github_output, "a", encoding="utf-8") as f:
        # 如果值包含换行符，使用 EOF 格式（多行输出）
        if "\n" in value:
            f.write(f"{name}<<EOF\n")
            f.write(value)
            f.write("\nEOF\n")
        else:
            f.write(f"{name}={value}\n")


def get_current_time_str():
    return datetime.now(timezone("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%SUTC%z")


T = TypeVar("T")
P = ParamSpec("P")


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (httpx.HTTPError,),
):
    """
    指数退避重试装饰器，支持同步和异步函数。

    Args:
            max_retries: 最大重试次数
            base_delay: 初始等待时间（秒）
            max_delay: 最大等待时间（秒）
            backoff_factor: 指数退避因子
            exceptions: 触发重试的异常类型
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                delay = base_delay
                last_exception = None
                for i in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if i == max_retries:
                            print(
                                f"达到最大重试次数 ({max_retries})，最后一次错误: {e}"
                            )
                            raise
                        print(
                            f"请求失败: {e}，正在进行第 {i + 1} 次重试，等待 {delay:.2f}s..."
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                if last_exception:
                    raise last_exception
                raise RuntimeError("Unreachable")

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                delay = base_delay
                last_exception = None
                for i in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if i == max_retries:
                            print(
                                f"达到最大重试次数 ({max_retries})，最后一次错误: {e}"
                            )
                            raise
                        print(
                            f"请求失败: {e}，正在进行第 {i + 1} 次重试，等待 {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                if last_exception:
                    raise last_exception
                raise RuntimeError("Unreachable")

            return sync_wrapper

    return decorator


def retry_call(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (httpx.HTTPError,),
    **kwargs: Any,
) -> T:
    """
    直接调用函数并进行重试，支持同步和异步。
    """
    _retry: Any = retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        exceptions=exceptions,
    )
    return _retry(func)(*args, **kwargs)
