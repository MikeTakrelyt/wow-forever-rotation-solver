"""
CASC Container, WDC5 DB2, and XFTH (v9) DBCache.bin Hotfix Reader for WoW Forever.
Reads directly from D:\\World of Warcraft\\_forever_ and D:\\World of Warcraft\\Data.
"""

import glob
import os
import struct
import zlib
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_WOW_ROOT = r"D:\World of Warcraft"
DEFAULT_FLAVOR_DIR = r"D:\World of Warcraft\_forever_"

# DB2Meta offsets in D:\World of Warcraft\_forever_\Wow.exe (Build 1.60.1.70888)
DB2_META_OFFSETS: Dict[str, int] = {
    "SpellName": 0x3BB3C30,
    "Spell": 0x3EB4C20,
    "SpellEffect": 0x3EAB520,
    "SpellMisc": 0x3EB51E0,
    "SpellPower": 0x3BB3A00,
    "SpellCooldowns": 0x3EC9900,
    "SpellLevels": 0x3EB5870,
    "SpellCastTimes": 0x3EAC680,
    "SpellDuration": 0x3EABF20,
    "SkillLine": 0x3BB2B20,
    "SkillLineAbility": 0x3BB2ED0,
    "Talent": 0x3B935C0,
    "TalentTab": 0x3B93670,
}


def _read_bits(buf_int: int, bit_offset: int, bit_count: int) -> int:
    if bit_count <= 0:
        return 0
    return (buf_int >> bit_offset) & ((1 << bit_count) - 1)


def _sign_extend(val: int, bits: int) -> int:
    if bits > 0 and (val & (1 << (bits - 1))):
        return val - (1 << bits)
    return val


class WoWForeverCASC:
    """Direct reader for WoW Forever CASC archives, WDC5 DB2 tables, and DBCache.bin hotfixes."""

    def __init__(
        self,
        wow_root: str = DEFAULT_WOW_ROOT,
        flavor_dir: str = DEFAULT_FLAVOR_DIR,
    ) -> None:
        self.wow_root = wow_root
        self.flavor_dir = flavor_dir
        self.data_dir = os.path.join(wow_root, "Data")
        self.exe_path = os.path.join(flavor_dir, "Wow.exe")
        self.dbcache_path = os.path.join(flavor_dir, "Cache", "ADB", "deDE", "DBCache.bin")

        with open(self.exe_path, "rb") as f:
            self.exe = f.read()

        self._pe_sections = self._parse_pe_sections()
        self.idx_entries = self._load_idx_files()
        self.build_cfg = self._load_build_config()
        self.encoding_data, self.ckey_pages = self._load_encoding()
        self.fdid_to_ckey = self._load_root()
        self.hotfixes_by_table_hash = self._load_dbcache()

    def _parse_pe_sections(self) -> List[Tuple[int, int, int, int]]:
        e_lfanew = struct.unpack_from("<I", self.exe, 0x3C)[0]
        num_sections = struct.unpack_from("<H", self.exe, e_lfanew + 6)[0]
        opt_hdr_size = struct.unpack_from("<H", self.exe, e_lfanew + 20)[0]
        sec_off = e_lfanew + 24 + opt_hdr_size
        sections = []
        for i in range(num_sections):
            _, vsize, rva, raw_size, raw_ptr = struct.unpack_from(
                "<8sIIII", self.exe, sec_off + i * 40
            )
            sections.append((rva, vsize, raw_ptr, raw_size))
        return sections

    def va_to_offset(self, va: int) -> Optional[int]:
        if not (0x140000000 <= va < 0x150000000):
            return None
        rva = va - 0x140000000
        for s_rva, _, s_ptr, s_size in self._pe_sections:
            if s_rva <= rva < s_rva + s_size:
                return s_ptr + (rva - s_rva)
        return None

    def _load_build_config(self) -> Dict[str, List[str]]:
        build_info_path = os.path.join(self.wow_root, ".build.info")
        build_key = None
        if os.path.exists(build_info_path):
            with open(build_info_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            headers = [h.split("!")[0] for h in lines[0].split("|")]
            for line in lines[1:]:
                parts = line.split("|")
                row = dict(zip(headers, parts))
                if row.get("Product") == "wowf":
                    build_key = row.get("Build Key")
                    break
            if not build_key and len(lines) > 1:
                parts = lines[1].split("|")
                row = dict(zip(headers, parts))
                build_key = row.get("Build Key")

        if not build_key:
            raise RuntimeError("Could not locate Build Key in .build.info")

        cfg_path = os.path.join(
            self.data_dir, "config", build_key[:2], build_key[2:4], build_key
        )
        cfg: Dict[str, List[str]] = {}
        with open(cfg_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = [x.strip() for x in line.split("=", 1)]
                    cfg[k] = v.split()
        return cfg

    def _load_idx_files(self) -> Dict[int, Tuple[bytes, int]]:
        data_sub = os.path.join(self.data_dir, "data")
        idx_files = sorted(glob.glob(os.path.join(data_sub, "*.idx")))
        latest_idx: Dict[int, str] = {}
        for p in idx_files:
            base = os.path.basename(p)
            bucket = int(base[:2], 16)
            latest_idx[bucket] = p

        idx_entries: Dict[int, Tuple[bytes, int]] = {}
        for bucket, p in latest_idx.items():
            with open(p, "rb") as f:
                buf = f.read()
            entries_size = struct.unpack_from("<I", buf, 32)[0]
            pos = 40
            idx_entries[bucket] = (buf[pos : pos + entries_size], entries_size // 18)
        return idx_entries

    def find_ekey(self, ekey_bytes: bytes) -> Optional[Tuple[int, int, int]]:
        prefix = ekey_bytes[:9]
        for _, (buf, count) in self.idx_entries.items():
            lo, hi = 0, count - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                off = mid * 18
                k = buf[off : off + 9]
                if k == prefix:
                    while mid > 0 and buf[(mid - 1) * 18 : (mid - 1) * 18 + 9] == prefix:
                        mid -= 1
                    off = mid * 18
                    idx_hi = buf[off + 9]
                    idx_lo = struct.unpack_from(">I", buf, off + 10)[0]
                    size = struct.unpack_from("<I", buf, off + 14)[0]
                    archive_id = (idx_hi << 2) | (idx_lo >> 30)
                    archive_offset = idx_lo & 0x3FFFFFFF
                    return archive_id, archive_offset, size
                elif k < prefix:
                    lo = mid + 1
                else:
                    hi = mid - 1
        return None

    def read_blte(self, archive_id: int, offset: int, size: int) -> bytes:
        p = os.path.join(self.data_dir, "data", f"data.{archive_id:03d}")
        with open(p, "rb") as f:
            f.seek(offset)
            raw = f.read(size)
        if raw[:4] != b"BLTE":
            if raw[30:34] == b"BLTE":
                raw = raw[30:]
            else:
                idx = raw.find(b"BLTE")
                if idx != -1:
                    raw = raw[idx:]
                else:
                    raise ValueError(f"BLTE magic not found at data.{archive_id:03d}:{offset}")

        header_size = struct.unpack_from(">I", raw, 4)[0]
        if header_size == 0:
            chunks = [(len(raw) - 8, len(raw) - 9)]
            data_pos = 8
        else:
            num_chunks = (
                (raw[9] << 16) | (raw[10] << 8) | raw[11]
            )
            chunks = []
            pos = 12
            for _ in range(num_chunks):
                c_size, u_size = struct.unpack_from(">II", raw, pos)
                chunks.append((c_size, u_size))
                pos += 24
            data_pos = header_size

        out = bytearray()
        for c_size, u_size in chunks:
            chunk = raw[data_pos : data_pos + c_size]
            data_pos += c_size
            mode = chunk[0:1]
            payload = chunk[1:]
            if mode == b"N":
                out.extend(payload)
            elif mode == b"Z":
                out.extend(zlib.decompress(payload))
            elif mode == b"E":
                # Zero-fill encrypted TactKey chunks so WDC5 section offsets stay aligned
                out.extend(b"\x00" * u_size)
            else:
                raise ValueError(f"Unsupported BLTE chunk mode: {mode!r}")
        return bytes(out)

    def _load_encoding(self) -> Tuple[bytes, List[Tuple[bytes, bytes]]]:
        enc_ekey = bytes.fromhex(self.build_cfg["encoding"][1])
        loc = self.find_ekey(enc_ekey)
        if not loc:
            raise RuntimeError("Could not locate CASC encoding table in .idx")
        enc_data = self.read_blte(*loc)
        (
            _,
            h_size_ckey,
            _,
            ckey_page_kb,
            _,
            ckey_page_count,
            _,
            _,
            espec_size,
        ) = struct.unpack_from(">BBBHHIIBI", enc_data, 2)
        pos = 22 + espec_size
        ckey_index_off = pos
        pos += ckey_page_count * 32
        ckey_pages_off = pos
        page_sz = ckey_page_kb * 1024

        pages = []
        for i in range(ckey_page_count):
            first_ckey = enc_data[ckey_index_off + i * 32 : ckey_index_off + i * 32 + h_size_ckey]
            p_start = ckey_pages_off + i * page_sz
            pages.append((first_ckey, enc_data[p_start : p_start + page_sz]))
        return enc_data, pages

    def ckey_to_ekey(self, ckey_bytes: bytes) -> Optional[bytes]:
        lo, hi = 0, len(self.ckey_pages) - 1
        page_idx = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.ckey_pages[mid][0] <= ckey_bytes:
                page_idx = mid
                lo = mid + 1
            else:
                hi = mid - 1
        page = self.ckey_pages[page_idx][1]
        p_pos = 0
        while p_pos + 22 <= len(page):
            key_cnt = page[p_pos]
            if key_cnt == 0:
                break
            ck = page[p_pos + 6 : p_pos + 22]
            if ck == ckey_bytes:
                return page[p_pos + 22 : p_pos + 38]
            p_pos += 6 + 16 + key_cnt * 16
        return None

    def _load_root(self) -> Dict[int, bytes]:
        root_ckey = bytes.fromhex(self.build_cfg["root"][0])
        root_ekey = self.ckey_to_ekey(root_ckey)
        if not root_ekey:
            raise RuntimeError("Could not resolve root CKey in encoding table")
        loc = self.find_ekey(root_ekey)
        if not loc:
            raise RuntimeError("Could not locate root EKey in .idx")
        root_data = self.read_blte(*loc)

        total_files, named_files = struct.unpack_from("<II", root_data, 12)
        allow_non_named = total_files != named_files
        pos = 24
        fdid_ckey: Dict[int, bytes] = {}
        while pos < len(root_data):
            num_rec, locale_flags, _, unk2, _ = struct.unpack_from("<IIIIB", root_data, pos)
            pos += 17
            deltas = struct.unpack_from(f"<{num_rec}i", root_data, pos)
            pos += 4 * num_rec
            ckeys_off = pos
            pos += 16 * num_rec
            has_names = not (allow_non_named and (unk2 & 0x10000000))
            if has_names:
                pos += 8 * num_rec
            # Locale flag 0x20 = deDE (or All)
            if locale_flags & 0x20:
                cur_id = -1
                for i, d in enumerate(deltas):
                    cur_id += d + 1
                    fdid_ckey[cur_id] = root_data[ckeys_off + i * 16 : ckeys_off + (i + 1) * 16]
        return fdid_ckey

    def _load_dbcache(self) -> Dict[int, Dict[int, Tuple[int, bytes]]]:
        by_th: Dict[int, Dict[int, Tuple[int, bytes]]] = {}
        if not os.path.exists(self.dbcache_path):
            return by_th
        with open(self.dbcache_path, "rb") as f:
            data = f.read()
        if len(data) < 44 or data[:4] != b"XFTH":
            return by_th
        pos = 44
        while pos + 32 <= len(data):
            magic, _, _, _, th, rid, dsz, status = struct.unpack_from(
                "<4sIiIIIIB3x", data, pos
            )
            pos += 32
            if magic != b"XFTH":
                break
            by_th.setdefault(th, {})[rid] = (status, data[pos : pos + dsz])
            pos += dsz
        return by_th

    def get_db2_bytes(self, fdid: int) -> bytes:
        ck = self.fdid_to_ckey[fdid]
        ek = self.ckey_to_ekey(ck)
        if not ek:
            raise KeyError(f"No EKey found for FDID {fdid}")
        loc = self.find_ekey(ek)
        if not loc:
            raise KeyError(f"No archive location found for FDID {fdid}")
        return self.read_blte(*loc)

    def parse_table(self, table_name: str) -> Dict[int, List[Any]]:
        """Parse a WDC5 DB2 table by name and overlay DBCache.bin hotfixes."""
        meta_pos = DB2_META_OFFSETS[table_name]
        (
            _,
            fdid,
            fld_cnt,
            _,
            file_fld_cnt,
            _,
            _,
        ) = struct.unpack_from("<QIIIIii", self.exe, meta_pos)
        ptrs = struct.unpack_from("<7Q", self.exe, meta_pos + 32)
        th, _, _ = struct.unpack_from("<III", self.exe, meta_pos + 92)
        arr_sizes = struct.unpack_from(f"<{file_fld_cnt}I", self.exe, self.va_to_offset(ptrs[4]))
        ftypes = struct.unpack_from(f"<{file_fld_cnt}I", self.exe, self.va_to_offset(ptrs[5]))
        fflags = struct.unpack_from(f"<{file_fld_cnt}I", self.exe, self.va_to_offset(ptrs[6]))

        b = self.get_db2_bytes(fdid)
        (
            _,
            w_fld_cnt,
            rec_size,
            _,
            _,
            _,
            _,
            _,
            _,
            flags,
            id_index,
            total_fld_cnt,
            _,
            _,
            fsi_size,
            com_size,
            pal_size,
            sec_cnt,
        ) = struct.unpack_from("<9IHH7I", b, 136)

        pos = 204
        sec_hdrs = []
        for _ in range(sec_cnt):
            sec_hdrs.append(struct.unpack_from("<Q8I", b, pos))
            pos += 40

        pos += total_fld_cnt * 4
        fsi = []
        for i in range(fsi_size // 24):
            fsi.append(struct.unpack_from("<HHIIIII", b, pos + i * 24))
        pos += fsi_size

        pallet_data = b[pos : pos + pal_size]
        pos += pal_size
        common_data = b[pos : pos + com_size]
        pos += com_size

        common_maps = []
        c_pos = 0
        for info in fsi:
            _, _, val_size, storage_type, _, _, _ = info
            cmap = {}
            if storage_type == 2 and val_size > 0:
                for _ in range(val_size // 8):
                    rid, rval = struct.unpack_from("<II", common_data, c_pos)
                    cmap[rid] = rval
                    c_pos += 8
            common_maps.append(cmap)

        records: Dict[int, List[Any]] = {}
        is_sparse = (flags & 0x01) != 0

        total_rec_bytes = sum(s[2] * rec_size for s in sec_hdrs)
        all_str_blocks = bytearray()
        if not is_sparse:
            for s in sec_hdrs:
                st_start = s[1] + s[2] * rec_size
                all_str_blocks.extend(b[st_start : st_start + s[3]])
        all_strings = bytes(all_str_blocks)
        cum_rec_bytes = 0

        for sec in sec_hdrs:
            (
                _,
                file_off,
                s_rec_cnt,
                s_str_size,
                off_rec_end,
                id_list_size,
                rel_size,
                off_map_cnt,
                copy_cnt,
            ) = sec
            s_pos = file_off
            if not is_sparse:
                rec_block = b[s_pos : s_pos + s_rec_cnt * rec_size]
                s_pos += s_rec_cnt * rec_size + s_str_size
            else:
                rec_block = b[s_pos:off_rec_end]
                s_pos = off_rec_end

            id_list = (
                struct.unpack_from(f"<{id_list_size // 4}I", b, s_pos)
                if id_list_size
                else None
            )
            s_pos += id_list_size

            copy_table = []
            for _ in range(copy_cnt):
                copy_table.append(struct.unpack_from("<II", b, s_pos))
                s_pos += 8

            off_map = []
            for _ in range(off_map_cnt):
                off_map.append(struct.unpack_from("<IH", b, s_pos))
                s_pos += 6

            rel_map = {}
            if rel_size:
                num_rel, _, _ = struct.unpack_from("<III", b, s_pos)
                r_pos = s_pos + 12
                for _ in range(num_rel):
                    fk_val, rec_idx = struct.unpack_from("<II", b, r_pos)
                    rel_map[rec_idx] = fk_val
                    r_pos += 8
                s_pos += rel_size

            off_map_ids = (
                struct.unpack_from(f"<{off_map_cnt}I", b, s_pos)
                if off_map_cnt
                else None
            )

            if is_sparse:
                for i in range(off_map_cnt):
                    rec_id = (
                        off_map_ids[i]
                        if off_map_ids
                        else (id_list[i] if id_list else i)
                    )
                    r_off, r_len = off_map[i]
                    raw_rec = b[r_off : r_off + r_len]
                    vals = self._unpack_flat_record(
                        raw_rec, fld_cnt, arr_sizes, ftypes, fflags
                    )
                    if rel_size > 0 or file_fld_cnt > fld_cnt:
                        vals.append(rel_map.get(i, 0))
                    records[rec_id] = vals
            else:
                pal_pos_by_field = []
                cur_pal = 0
                for info in fsi:
                    pal_pos_by_field.append(cur_pal)
                    if info[3] in (3, 4):
                        cur_pal += info[2]

                for i in range(s_rec_cnt):
                    raw_rec = rec_block[i * rec_size : (i + 1) * rec_size]
                    rec_int = int.from_bytes(raw_rec, "little")
                    rec_id = id_list[i] if id_list else None
                    vals: List[Any] = []
                    for fi in range(w_fld_cnt):
                        (
                            f_off_bits,
                            f_size_bits,
                            _,
                            storage_type,
                            v1,
                            _,
                            v3,
                        ) = fsi[fi]
                        ft = ftypes[fi]
                        cnt = arr_sizes[fi]
                        signed = (fflags[fi] & 2) != 0

                        if storage_type == 0:
                            elem_bits = f_size_bits // cnt
                            fvals = []
                            for ei in range(cnt):
                                raw_v = _read_bits(
                                    rec_int, f_off_bits + ei * elem_bits, elem_bits
                                )
                                if ft == 2:
                                    fvals.append(raw_v)
                                elif ft == 3:
                                    fvals.append(
                                        struct.unpack("<f", struct.pack("<I", raw_v))[0]
                                    )
                                else:
                                    fvals.append(
                                        _sign_extend(raw_v, elem_bits)
                                        if signed
                                        else raw_v
                                    )
                            vals.append(fvals[0] if cnt == 1 else fvals)
                        elif storage_type == 1:
                            raw_v = _read_bits(rec_int, f_off_bits, f_size_bits)
                            if v3 != 0 or signed:
                                raw_v = _sign_extend(raw_v, f_size_bits)
                            vals.append(raw_v)
                        elif storage_type == 2:
                            raw_v = common_maps[fi].get(rec_id, v1)
                            if ft == 3:
                                raw_v = struct.unpack("<f", struct.pack("<I", raw_v))[0]
                            elif signed:
                                raw_v = _sign_extend(raw_v, 32)
                            vals.append(raw_v)
                        elif storage_type == 3:
                            idx = _read_bits(rec_int, f_off_bits, f_size_bits)
                            p_off = pal_pos_by_field[fi] + idx * 4
                            if ft == 3:
                                raw_v = struct.unpack_from("<f", pallet_data, p_off)[0]
                            else:
                                raw_v = struct.unpack_from(
                                    "<i" if signed else "<I", pallet_data, p_off
                                )[0]
                            vals.append(raw_v)
                        elif storage_type == 4:
                            idx = _read_bits(rec_int, f_off_bits, f_size_bits)
                            p_off = pal_pos_by_field[fi] + idx * 4 * v3
                            fvals = []
                            for ei in range(v3):
                                if ft == 3:
                                    fvals.append(
                                        struct.unpack_from(
                                            "<f", pallet_data, p_off + ei * 4
                                        )[0]
                                    )
                                else:
                                    fvals.append(
                                        struct.unpack_from(
                                            "<i" if signed else "<I",
                                            pallet_data,
                                            p_off + ei * 4,
                                        )[0]
                                    )
                            vals.append(fvals)
                        elif storage_type == 5:
                            raw_v = _sign_extend(
                                _read_bits(rec_int, f_off_bits, f_size_bits),
                                f_size_bits,
                            )
                            vals.append(raw_v)

                    if rec_id is None:
                        rec_id = vals[id_index]

                    for fi in range(w_fld_cnt):
                        if ftypes[fi] == 2 and isinstance(vals[fi], int):
                            str_off = vals[fi]
                            if str_off == 0:
                                vals[fi] = ""
                            else:
                                rel_off = (
                                    cum_rec_bytes
                                    + (i * rec_size)
                                    + (fsi[fi][0] // 8)
                                    + str_off
                                    - total_rec_bytes
                                )
                                if 0 <= rel_off < len(all_strings):
                                    end = all_strings.find(b"\x00", rel_off)
                                    vals[fi] = all_strings[rel_off:end].decode(
                                        "utf-8", errors="replace"
                                    )
                                else:
                                    vals[fi] = ""

                    if rel_size > 0 or file_fld_cnt > fld_cnt:
                        vals.append(rel_map.get(i, 0))
                    records[rec_id] = vals

                cum_rec_bytes += s_rec_cnt * rec_size

            for dst_id, src_id in copy_table:
                if src_id in records:
                    records[dst_id] = list(records[src_id])

        # Apply DBCache.bin hotfixes
        hotfixes = self.hotfixes_by_table_hash.get(th, {})
        for rid, (status, raw_rec) in hotfixes.items():
            if status == 1 and len(raw_rec) > 0:
                vals = self._unpack_flat_record(
                    raw_rec, fld_cnt, arr_sizes, ftypes, fflags, allow_parent_fk=True
                )
                records[rid] = vals
            elif status == 2:
                records.pop(rid, None)

        return records

    @staticmethod
    def _unpack_flat_record(
        raw_rec: bytes,
        fld_cnt: int,
        arr_sizes: Tuple[int, ...],
        ftypes: Tuple[int, ...],
        fflags: Tuple[int, ...],
        allow_parent_fk: bool = False,
    ) -> List[Any]:
        vals: List[Any] = []
        p = 0
        for fi in range(fld_cnt):
            ft = ftypes[fi]
            cnt = arr_sizes[fi]
            signed = (fflags[fi] & 2) != 0
            fvals = []
            for _ in range(cnt):
                if ft == 2:
                    end = raw_rec.find(b"\x00", p)
                    if end == -1:
                        end = len(raw_rec)
                    s_val = raw_rec[p:end].decode("utf-8", errors="replace")
                    p = min(end + 1, len(raw_rec))
                    fvals.append(s_val)
                elif ft == 0:
                    fvals.append(
                        struct.unpack_from("<i" if signed else "<I", raw_rec, p)[0]
                    )
                    p += 4
                elif ft == 3:
                    fvals.append(struct.unpack_from("<f", raw_rec, p)[0])
                    p += 4
                elif ft == 4:
                    fvals.append(
                        struct.unpack_from("<b" if signed else "<B", raw_rec, p)[0]
                    )
                    p += 1
                elif ft == 5:
                    fvals.append(
                        struct.unpack_from("<h" if signed else "<H", raw_rec, p)[0]
                    )
                    p += 2
            vals.append(fvals[0] if cnt == 1 else fvals)
        if allow_parent_fk and len(raw_rec) == p + 4:
            vals.append(struct.unpack_from("<I", raw_rec, p)[0])
        return vals
