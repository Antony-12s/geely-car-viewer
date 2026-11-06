# Geely Car Viewer

(เดิมชื่อ EX5 Viewer) · ดูว่ามีอะไรใหม่ใน [CHANGELOG.md](CHANGELOG.md)

ดูจอรถ Geely EX5 บนคอม: **จอกลาง + HUD + หน้าปัด** ในหน้าต่างเดียว ต่อผ่าน adb ทาง Wi‑Fi หรือ USB
Mirror the Geely EX5 main screen, HUD and instrument cluster in one window over adb (Wi‑Fi or USB).

## ใช้งาน / Usage

1. เปิด adb บนหัวรถ (EX5 ใช้พอร์ต `5566`) / enable adb on the head unit
2. เปิด Geely Car Viewer → เลือก Wi‑Fi (พิมพ์ IP) หรือ USB → **เชื่อมต่อ**
3. สวิตช์ **ควบคุม** ใต้จอกลาง = คลิก/ลากบนภาพแล้วกดในรถจริง
4. ⚙ ตั้งค่า: ภาษา, ธีม, ขนาดหน้าต่าง, fps, รีเฟรชหน้าปัด, กราฟเน็ต ฯลฯ (บันทึกเองทันที)

| OS | ไฟล์ | หมายเหตุ |
|---|---|---|
| Windows 10/11 x64 | `GeelyCarViewer-windows-x64.zip` | แตกไฟล์แล้วเปิด `GeelyCarViewer.exe` (SmartScreen: More info → Run anyway) |
| Linux x86_64 | `GeelyCarViewer-linux-x86_64.tar.gz` | แตกไฟล์ → `./GeelyCarViewer` · `./install-linux.sh` เพิ่มเข้าเมนูแอป |
| macOS (Apple Silicon) | `GeelyCarViewer-macos-arm64.zip` | ไม่ได้ sign: คลิกขวา → Open ครั้งแรก |

## อะไรทำงานยังไง / How it works

- **จอกลาง/HUD:** คุยกับ `scrcpy-server` 5.0.1 ตรง ๆ (ไม่ต้องลง scrcpy) ถอดรหัส H.264 ด้วย PyAV
  จับภาพเต็ม 2560×1600 เสมอ: ถ้าลดขนาดตอนจับ wallpaper วิดีโอของรถจะซูมเพี้ยน
- **หน้าปัด:** เป็นเครื่อง Linux แยก (`198.18.44.2`) ต่อด้วย SSH ผ่าน `adb shell su 0 toybox nc`
  ดึงภาพ `LayerManagerControl dump surface` ทุก 0.5–5 วิ (ต้องมี root บนหัวรถ)
- **ตัวเลขเน็ต:** นับเฉพาะทราฟฟิกของแอปนี้ · GPU คอม: Intel/NVIDIA บน Linux เท่านั้น · GPU หัวรถ: แสดงถ้ารถเปิดไฟล์ให้อ่าน
- **EX2:** จอกลางใช้ทางเดียวกัน หน้าปัดยังไม่รองรับ (ยังไม่รู้ว่าอยู่ระบบไหน)

## Build จากซอร์ส

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pyinstaller pytest
.venv/bin/python scripts/fetch_deps.py          # scrcpy-server (hash-checked) + adb
.venv/bin/python -m pytest -q tests/test_core.py
.venv/bin/python -m ex5viewer                   # run
.venv/bin/pyinstaller ex5viewer.spec            # dist/GeelyCarViewer
```

Release: push tag `vX.Y.Z` → GitHub Actions builds Windows / Linux / macOS, runs `--selftest` on each, attaches the zips.

Bundled: [scrcpy-server](https://github.com/Genymobile/scrcpy) (Apache-2.0), Android SDK Platform-Tools `adb` (see `NOTICE.txt` in the bundle).
