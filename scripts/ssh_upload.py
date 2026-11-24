#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH文件上传CLI工具 v3.1

支持通过别名上传文件，SFTP 高级功能：断点续传、目录递归上传、进度显示

用法：
    python ssh_upload.py <alias> <local_path> <remote_path> [options]

示例：
    # 上传单个文件
    python ssh_upload.py prod-web-01 ./app.tar.gz /tmp/

    # 断点续传（大文件推荐）
    python ssh_upload.py prod-web-01 ./large-file.iso /tmp/ --resume

    # 上传整个目录
    python ssh_upload.py prod-web-01 ./dist/ /var/www/html/ --recursive

    # 上传目录 + 断点续传
    python ssh_upload.py prod-web-01 ./data/ /opt/data/ --recursive --resume
"""

import sys
import os
import json
import argparse
import re
import time
from typing import TextIO

# 添加lib到路径
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, 'lib'))

from output_limits import ProgressEmitter


def _fix_remote_path(path):
    """修复被 MSYS bash 转换的远程路径（Windows 环境）"""
    # 检测 MSYS 路径转换：X:/... 或 X:\...
    if re.match(r'^[A-Za-z]:[/\\]', path):
        print(json.dumps({
            'success': False,
            'error': f'Remote path looks like a Windows path (MSYS conversion): {path}. '
                     f'Use MSYS_NO_PATHCONV=1 prefix or quote the path.'
        }, ensure_ascii=True, indent=2), file=sys.stderr)
        sys.exit(1)
    return path


def make_progress_callback(
    explicit: bool | None,
    *,
    stream: TextIO = sys.stderr,
    clock=time.monotonic,
):
    emitter = ProgressEmitter(stream, enabled=explicit, clock=clock)
    if not emitter.enabled:
        return None

    def callback(progress):
        emitter.emit(
            'upload',
            progress.transferred_bytes,
            progress.total_bytes,
            file_path=progress.file_path,
        )

    return callback


def use_native_upload(params, *, resume=False, recursive=False, progress=None, remote_path=None):
    """Select by required capabilities, never by file size."""
    # Legacy SCP interprets remote paths through a shell. Keep unusual paths on SFTP.
    if remote_path is not None and not re.fullmatch(r'[a-zA-Z0-9_./+~-]+', remote_path):
        return False
    return bool(params.get('key_file') and not params.get('password')
                and not resume and not recursive and progress is not True)


def _legacy_main(argv=None):
    parser = argparse.ArgumentParser(description='SSH file upload tool v3.1')
    parser.add_argument('alias', help='SSH host alias from ~/.ssh/config')
    parser.add_argument('local_path', help='Local file or directory path')
    parser.add_argument('remote_path', help='Remote file or directory path')
    parser.add_argument('--resume', action='store_true',
                        help='Enable resume for interrupted transfers')
    parser.add_argument('--recursive', action='store_true',
                        help='Upload directory recursively')
    progress_group = parser.add_mutually_exclusive_group()
    progress_group.add_argument('--progress', dest='progress', action='store_true',
                                help='Enable bounded JSONL progress on stderr')
    progress_group.add_argument('--no-progress', dest='progress', action='store_false',
                                help='Disable progress output')
    parser.set_defaults(progress=None)

    args = parser.parse_args(argv)
    remote_path = _fix_remote_path(args.remote_path)

    client = ssh_client = sftp = None
    try:
        # 加载配置
        from config_v3 import SSHConfigLoaderV3
        loader = SSHConfigLoaderV3()
        params = loader.get_connection_params(args.alias)

        use_native = use_native_upload(
            params, resume=args.resume, recursive=args.recursive,
            progress=args.progress, remote_path=remote_path,
        )

        local_path = os.path.abspath(args.local_path)
        if not os.path.isfile(local_path) and not os.path.isdir(local_path):
            raise FileNotFoundError(local_path)
        if os.path.isdir(local_path) and not args.recursive:
            raise ValueError('Directory upload requires --recursive')

        if use_native:
            # 使用原生 SSH（简单上传，性能更好）
            client = loader.from_alias(args.alias)
            local_path = os.path.abspath(args.local_path)

            if not os.path.isfile(local_path):
                print(json.dumps({
                    'success': False,
                    'error': f'Path not found: {args.local_path}'
                }, ensure_ascii=True, indent=2), file=sys.stderr)
                sys.exit(1)

            result = client.upload(local_path, remote_path, show_progress=args.progress is True)
            print(json.dumps({
                'success': result.success,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'exit_code': result.exit_code
            }, ensure_ascii=True, indent=2))
            sys.exit(0 if result.success else 1)
        else:
            # 使用 Paramiko SFTP（支持断点续传、递归上传等高级功能）
            from paramiko_client import ParamikoClient
            client = ParamikoClient(
                host=params['hostname'],
                user=params['user'],
                port=params['port'],
                password=params.get('password'),
                key_file=params.get('key_file'),
                timeout=30,
                jump_hosts=loader.resolve_jump_hosts(params.get('proxy_jump')),
                transfer_timeout=None  # 大文件传输不设超时限制
            )

            # 获取 SSH 连接和 SFTP
            ssh_client = client._get_connection()
            sftp = ssh_client.open_sftp()

            # 设置 SFTP 超时（大文件传输使用无限制）
            sftp.get_channel().settimeout(None)

            # 创建传输器
            from sftp_transfer import SFTPTransfer
            cb = make_progress_callback(args.progress)
            transfer = SFTPTransfer(sftp, progress_callback=cb)

            local_path = os.path.abspath(args.local_path)

        # 判断是文件还是目录
        if os.path.isdir(local_path):
            if not args.recursive:
                print(json.dumps({
                    'success': False,
                    'error': f'"{args.local_path}" is a directory. Use --recursive to upload directories.'
                }, ensure_ascii=True, indent=2), file=sys.stderr)
                sys.exit(1)
            result = transfer.upload_directory(local_path, remote_path,
                                               resume=args.resume)
        elif os.path.isfile(local_path):
            result = transfer.upload_file(local_path, remote_path,
                                          resume=args.resume)
        else:
            print(json.dumps({
                'success': False,
                'error': f'Path not found: {args.local_path}'
            }, ensure_ascii=True, indent=2), file=sys.stderr)
            sys.exit(1)

        # 输出结果
        output = result.to_dict()
        print(json.dumps(output, ensure_ascii=True, indent=2))
        sys.exit(0 if result.success else 1)

    except FileNotFoundError as e:
        print(json.dumps({
            'success': False,
            'error': f'File not found: {e}'
        }, ensure_ascii=True, indent=2), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({
            'success': False,
            'error': f'Invalid alias: {e}'
        }, ensure_ascii=True, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': f'Upload error: {e}'
        }, ensure_ascii=True, indent=2), file=sys.stderr)
        sys.exit(1)

    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if client is not None and getattr(client, 'jump_hosts', None):
            if ssh_client is not None:
                try:
                    ssh_client.close()
                except Exception:
                    pass
            client._cleanup_jump_connections()


def main(argv=None):
    from ssh_skill import delegate_legacy_entrypoint

    arguments = sys.argv[1:] if argv is None else list(argv)
    return delegate_legacy_entrypoint(
        'upload', arguments, legacy_main=_legacy_main
    )


if __name__ == '__main__':
    raise SystemExit(main())
