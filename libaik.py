#
# Copyright (C) 2022 Sebastiano Barezzi
#
# SPDX-License-Identifier: Apache-2.0
#
"""AIK wrapper library (reimplemented with magiskboot)."""

from pathlib import Path
from platform import system
from shutil import which
from subprocess import check_output, STDOUT, CalledProcessError
from tempfile import TemporaryDirectory
from typing import Optional
import os
import shutil


ALLOWED_OS = ["Linux", "Darwin"]


class AIKImageInfo:
    def __init__(
        self,
        base_address: Optional[str],
        board_name: Optional[str],
        cmdline: Optional[str],
        dt: Optional[Path],
        dtb: Optional[Path],
        dtb_offset: Optional[str],
        dtbo: Optional[Path],
        header_version: Optional[str],
        image_type: Optional[str],
        kernel: Optional[Path],
        kernel_offset: Optional[str],
        origsize: Optional[str],
        os_version: Optional[str],
        pagesize: Optional[str],
        ramdisk: Optional[Path],
        ramdisk_compression: Optional[str],
        ramdisk_offset: Optional[str],
        sigtype: Optional[str],
        tags_offset: Optional[str],
    ):
        self.kernel = kernel
        self.dt = dt
        self.dtb = dtb
        self.dtbo = dtbo
        self.ramdisk = ramdisk
        self.base_address = base_address
        self.board_name = board_name
        self.cmdline = cmdline
        self.dtb_offset = dtb_offset
        self.header_version = header_version
        self.image_type = image_type
        self.kernel_offset = kernel_offset
        self.origsize = origsize
        self.os_version = os_version
        self.pagesize = pagesize
        self.ramdisk_compression = ramdisk_compression
        self.ramdisk_offset = ramdisk_offset
        self.sigtype = sigtype
        self.tags_offset = tags_offset

    def __str__(self):
        return (
            f"base address: {self.base_address}\n"
            f"board name: {self.board_name}\n"
            f"cmdline: {self.cmdline}\n"
            f"dtb offset: {self.dtb_offset}\n"
            f"header version: {self.header_version}\n"
            f"image type: {self.image_type}\n"
            f"kernel offset: {self.kernel_offset}\n"
            f"original size: {self.origsize}\n"
            f"os version: {self.os_version}\n"
            f"page size: {self.pagesize}\n"
            f"ramdisk compression: {self.ramdisk_compression}\n"
            f"ramdisk offset: {self.ramdisk_offset}\n"
            f"sigtype: {self.sigtype}\n"
            f"tags offset: {self.tags_offset}\n"
        )


class AIKManager:
    """Manage boot image extraction/repacking using magiskboot."""

    def __init__(self):
        if system() not in ALLOWED_OS:
            raise NotImplementedError(f"{system()} is not supported")

        if which("magiskboot") is None:
            raise RuntimeError("magiskboot is not installed")
        if which("cpio") is None:
            raise RuntimeError("cpio package is not installed")

        self.tempdir = TemporaryDirectory()
        self.path = Path(self.tempdir.name)
        self.images_path = self.path / "split_img"
        self.ramdisk_path = self.path / "ramdisk"

    def unpackimg(self, image: Path, ignore_ramdisk_errors: bool = False):
        """Extract recovery image using magiskboot."""
        prefix = image.name

        # Create output directories
        self.images_path.mkdir(exist_ok=True)
        self.ramdisk_path.mkdir(exist_ok=True)

        # 1. Unpack boot image using magiskboot (must run in images_path)
        orig_cwd = os.getcwd()
        abs_image_path = image.absolute()  # 转为绝对路径，避免在 chdir 后找不到
        try:
            os.chdir(self.images_path)
            # -h 生成 header 文件
            cmd = ["magiskboot", "unpack", "-h", str(abs_image_path)]
            output = check_output(cmd, stderr=STDOUT, universal_newlines=True, encoding="utf-8")
        except CalledProcessError as e:
            returncode = e.returncode
            output = e.output
            if returncode != 0:
                if ignore_ramdisk_errors:
                    try:
                        shutil.rmtree(self.ramdisk_path)
                    except Exception:
                        pass
                else:
                    raise RuntimeError(f"magiskboot extraction failed, return code {returncode}, output {output[-1000:]}")
        else:
            returncode = 0
        finally:
            os.chdir(orig_cwd)
        raise Exception(f"{self.images_path}; {orig_cwd}")

        # 2. Read header file to get all parameters
        header_file = self.images_path / "header"
        if not header_file.exists():
            raise RuntimeError("magiskboot did not generate header file")

        params = self._parse_header_file(header_file)

        # 3. Write fragment files (prefix-*) so that _get_current_extracted_info can read them
        self._write_fragment_files(prefix, params)

        # 4. Extract ramdisk.cpio to ramdisk folder (if present)
        ramdisk_cpio = self.images_path / "ramdisk.cpio"
        if ramdisk_cpio.exists() and ramdisk_cpio.stat().st_size > 0:
            try:
                # 在 ramdisk_path 下执行解包，使用相对路径 ../ramdisk.cpio
                subprocess_cmd = ["magiskboot", "cpio", "../ramdisk.cpio", "extract"]
                check_output(
                    subprocess_cmd,
                    cwd=str(self.ramdisk_path),
                    stderr=STDOUT,
                    universal_newlines=True,
                )
                raise Exception(str(__import__("os").listdir()))
                check_output(["patch_build.sh"], stderr=STDOUT, universal_newlines=True, encoding="utf-8")
            except CalledProcessError as e:
                if ignore_ramdisk_errors:
                    shutil.rmtree(self.ramdisk_path, ignore_errors=True)
                    self.ramdisk_path.mkdir(exist_ok=True)
                else:
                    raise RuntimeError(f"Ramdisk extraction failed: {e.output}") from e
        else:
            # No ramdisk or empty
            if not ignore_ramdisk_errors:
                raise RuntimeError("No ramdisk found in image")

        # Return extracted info (compatible with original AIK)
        return self._get_current_extracted_info(prefix)

    def repackimg(self):
        """Repack using magiskboot."""
        # 我们假定原始镜像在 self.path 下（复制一份），或者我们可以从 images_path 取信息
        # 更可靠：从 images_path 找 header，用其中的信息重建
        # 但为了简单，我们仍然使用原始镜像（用户需要自己拷贝进去，或我们在 unpack 时保存）
        # 这里我们尝试找 self.path 下的 .img 文件
        orig_img = next(self.path.glob("*.img"), None)
        if not orig_img:
            # 如果没有，尝试使用 images_path 中的 kernel 和 ramdisk 等构建
            # 但 magiskboot repack 需要原始镜像作为模板
            raise RuntimeError("No original image found to repack. Please copy the original image to the temp directory.")
        
        out_img = self.path / "repacked.img"
        # 使用 images_path 中的文件
        kernel = self.images_path / "kernel"
        ramdisk = self.images_path / "ramdisk.cpio"
        dtb = self.images_path / "dtb"

        # 构建命令，注意当前目录需要包含组件文件
        # 最好在 images_path 中执行 repack，但我们需要指定原始镜像路径
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.images_path)
            cmd = ["magiskboot", "repack", str(orig_img), str(out_img)]
            # 如果 kernel 等存在，它们已经在当前目录，会自动被识别
            # 但有时需要明确指定 --kernel 等，但 repack 默认使用当前目录下的文件
            # 所以我们不额外加参数
            output = check_output(cmd, stderr=STDOUT, universal_newlines=True, encoding="utf-8")
        except CalledProcessError as e:
            raise RuntimeError(f"Repack failed: {e.output}") from e
        finally:
            os.chdir(orig_cwd)

        return output

    def cleanup(self):
        """Remove temporary directory."""
        try:
            self.tempdir.cleanup()
        except Exception:
            pass

    # ---------------------- Internal helpers ----------------------

    def _parse_header_file(self, header_path: Path) -> dict:
        """Parse magiskboot header file (key=value lines)."""
        params = {}
        with open(header_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                params[key.strip()] = value.strip()
        return params

    def _write_fragment_files(self, prefix: str, params: dict):
        """Write split_img/prefix-* files from parsed header."""
        # Map magiskboot header keys to AIK fragment names
        mapping = {
            "BASE": "base",
            "BOARD_NAME": "board_name",
            "CMDLINE": "cmdline",
            "PAGE_SIZE": "pagesize",
            "HEADER_VERSION": "header_version",
            "OS_VERSION": "os_version",
            "RAMDISK_FMT": "ramdiskcomp",
            "SIGNATURE": "sigtype",
            "KERNEL_ADDR": "kernel_offset",
            "RAMDISK_ADDR": "ramdisk_offset",
            "TAGS_ADDR": "tags_offset",
            "DTB_OFFSET": "dtb_offset",
        }

        fragments = {
            "base": "0x10000000",
            "board_name": "",
            "cmdline": "",
            "dtb_offset": "0",
            "header_version": "0",
            "image_type": "boot",
            "kernel_offset": "0x00008000",
            "origsize": "0",
            "os_version": "0",
            "pagesize": "2048",
            "ramdiskcomp": "unknown",
            "ramdisk_offset": "0x01000000",
            "sigtype": "",
            "tags_offset": "0x00000100",
        }

        # Override with parsed values
        for magisk_key, aik_key in mapping.items():
            if magisk_key in params:
                fragments[aik_key] = params[magisk_key]

        # Special: compute base from kernel_addr if not directly provided
        if "kernel_offset" in fragments and fragments["kernel_offset"]:
            if "KERNEL_ADDR" in params:
                kernel_addr = int(params["KERNEL_ADDR"], 16)
                kernel_offset = int(fragments["kernel_offset"], 16)
                base = kernel_addr - kernel_offset
                fragments["base"] = hex(base)

        # Write each fragment
        for key, value in fragments.items():
            fragment_file = self.images_path / f"{prefix}-{key}"
            fragment_file.write_text(value + "\n")

    def _get_current_extracted_info(self, prefix: str):
        """Same as original - reads fragment files and returns AIKImageInfo."""
        def _read(fragment, default=None):
            file = self.images_path / f"{prefix}-{fragment}"
            if not file.exists():
                return default
            return file.read_text().strip()

        def _path(fragment, check_size=False):
            p = self.images_path / f"{prefix}-{fragment}"
            if not p.is_file():
                return None
            if check_size and p.stat().st_size == 0:
                return None
            return p

        return AIKImageInfo(
            base_address=_read("base"),
            board_name=_read("board_name"),
            cmdline=_read("cmdline") or _read("vendor_cmdline"),
            dt=_path("dt", check_size=True),
            dtb=_path("dtb", check_size=True),
            dtb_offset=_read("dtb_offset"),
            dtbo=_path("dtbo", check_size=True) or _path("recovery_dtbo", check_size=True),
            header_version=_read("header_version", default="0"),
            image_type=_read("image_type"),
            kernel=_path("kernel", check_size=True),
            kernel_offset=_read("kernel_offset"),
            origsize=_read("origsize"),
            os_version=_read("os_version"),
            pagesize=_read("pagesize"),
            ramdisk=self.ramdisk_path if self.ramdisk_path.is_dir() else None,
            ramdisk_compression=_read("ramdiskcomp") or _read("vendor_ramdiskcomp"),
            ramdisk_offset=_read("ramdisk_offset"),
            sigtype=_read("sigtype"),
            tags_offset=_read("tags_offset"),
        )
