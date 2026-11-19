# GIGABYTE AERO / AORUS Keyboard RGB Hardware Protocol Specification

This document details the reverse-engineered communications protocol between the operating system and the internal keyboard lighting microcontroller on **GIGABYTE AERO & AORUS** series laptops (specifically validated on the **GIGABYTE AERO X16 1WH**).

---

## 1. Device Architecture & Identification

The keyboard and backlighting system are exposed as a composite USB device managed by an **ITE IT8298 / IT8233** Embedded Controller / MCU.

```text
Host (Windows / Linux)
       │
       ▼ USB Composite Device (VID: 0x0414, PID: 0x8104)
 ┌─────┴────────────────────────────────────────────────────────┐
 │ Interface 0 (MI_00) : HID Standard Keyboard Interface       │
 │ Interface 1 (MI_01) : Vendor-defined HID Communication       │
 │ Interface 2 (MI_02) : Consumer Control / Wireless Radio     │
 │ Interface 3 (MI_03) : Vendor-defined Auxiliary Control      │
 │ Interface 4 (MI_04) : Windows Dynamic Lighting (LampArray)   │
 └─────┬────────────────────────────────────────────────────────┘
       │
       ▼
 ITE IT8298 Microcontroller (Firmware: 0x3033 / 0x0BD9)
       │
       ▼
 Single-Zone Keyboard RGB LED Matrix + Chassis Status Indicator
```

### Hardware IDs
* **USB Vendor ID (VID):** `0x0414` (Giga-Byte Technology Co., Ltd.)
* **USB Product ID (PID):** `0x8104`
* **Device Instance Path:** `\\?\HID#VID_0414&PID_8104&MI_00` through `MI_04`
* **LampArray Notification GUID:** `{4D1E55B2-F16F-11CF-88CB-001111000030}`

---

## 2. Communications Layer

Communication is performed over USB HID using **9-byte HID Feature Reports** via the Windows Win32 API:
```c
BOOL HidD_SetFeature(
    HANDLE HidDeviceObject,
    PVOID  ReportBuffer,
    ULONG  ReportBufferLength // 9 Bytes
);
```

### 9-Byte Packet Structure
Every command packet sent to the ITE IT8298 MCU adheres to a strict 9-byte structure:

| Byte Index | Field Name | Description |
| :---: | :--- | :--- |
| **0** | `ReportID` | Always `0x00` |
| **1** | `Command` | Primary command opcode (e.g., `0x14` for Color, `0x08` for Mode/Pattern) |
| **2** | `Option` | Sub-option flag (typically `0x00`) |
| **3** | `Param1` | Mode ID (in `0x08`) or Sub-zone (in `0x14`, `0x01` for primary zone) |
| **4** | `Param2` | Animation Speed (in `0x08`) or **Red** channel (in `0x14`) |
| **5** | `Param3` | Brightness Level (in `0x08`) or **Green** channel (in `0x14`) |
| **6** | `Param4` | Color Index (in `0x08`) or **Blue** channel (in `0x14`) |
| **7** | `Direction` | Animation direction (typically `0x00`) |
| **8** | `Checksum` | Calculated 8-bit checksum byte |

---

## 3. Checksum Algorithm

The MCU validates each packet by computing an 8-bit inverted sum of bytes 1 through 7:

$$\text{Checksum} = \left(255 - \sum_{i=1}^7 \text{Buffer}[i]\right) \pmod{256}$$

### Implementation (PowerShell / Python / C#)
```csharp
byte CalculateChecksum(byte[] buffer) {
    int sum = 0;
    for (int i = 1; i < 8; i++) {
        sum += buffer[i];
    }
    return (byte)((255 - sum) & 0xFF);
}
```

```python
def calculate_checksum(packet: list[int]) -> int:
    return (255 - sum(packet[1:8])) & 0xFF
```

---

## 4. Primary Command Sequence

Setting a lighting effect requires a two-step transmission with a hardware timing delay (SpinWait / 15-25ms):

### Step 1: Set Target RGB Color (`Command = 0x14`)
This packet sets the active 24-bit RGB palette in the MCU registers:

```text
[0x00, 0x14, 0x00, 0x01, <Red>, <Green>, <Blue>, 0x00, <Checksum>]
```
* Example for **Cyan (`#00FFFF`)**:
  * Byte 4 (Red): `0x00`
  * Byte 5 (Green): `0xFF`
  * Byte 6 (Blue): `0xFF`
  * Checksum: `(255 - (0x14 + 0x00 + 0x01 + 0x00 + 0xFF + 0xFF + 0x00)) & 0xFF = 0xEC`
  * *Correction:* an earlier version of this document gave `0xEB` here, which disagrees with the
    formula in section 3 by one. `0xEC` is what the formula gives. Which one the chip accepts
    is still unconfirmed; `aero-rgb probe --checksum` tests both (see [HARDWARE_TESTING.md](HARDWARE_TESTING.md)).

### Step 2: SpinWait Delay
Wait **15–25ms** for MCU register latching:
```csharp
SpinWait.SpinUntil(() => false, 20);
```

### Step 3: Set Animation Pattern / Mode (`Command = 0x08`)
This packet commits the pattern engine, speed, and brightness:

```text
[0x00, 0x08, 0x00, <PatternID>, <Speed>, <Brightness>, 0x00, 0x00, <Checksum>]
```

---

## 5. Pattern Mode Mapping Table

The firmware maps internal pattern modes as follows:

| Mode Name | User/API ID | Hardware Pattern ID (`Param1`) | Supported Parameters |
| :--- | :---: | :---: | :--- |
| **Static / Still** | `0` | `0x01` | Fixed RGB Color, Brightness (0–10) |
| **Breathe / Pulse** | `1` | `0x02` | RGB Color, Speed (1–10), Brightness (1–10) |
| **Color Cycle (Rainbow)**| `78` | `0x03` | Speed (1–10), Brightness (1–10) |
| **RGB Pulse** | `84` | `0x04` | Speed (1–10), Brightness (1–10) |
| **Cycle Pulse** | `92` | `0x05` | Speed (1–10), Brightness (1–10) |

*Note: For Static mode, Speed is set to `0x02` and Brightness is passed as `0x20 | (bri & 0x0F)` or directly through the brightness byte.*

---

## 6. Windows Dynamic Lighting (WinRT `LampArray`)

Windows 11 natively discovers Interface 4 (`MI_04`) as a standard **HID LampArray**:

* **WinRT Type:** `Windows.Devices.Lights.LampArray`
* **Device Selector:**
  ```text
  System.Devices.InterfaceClassGuid:="{4D1E55B2-F16F-11CF-88CB-001111000030}" 
  AND System.Devices.InterfaceEnabled:=True 
  AND System.DeviceInterface.Hid.UsagePage:=89 
  AND System.DeviceInterface.Hid.UsageId:=1
  ```
* **Attributes:**
  * `LampCount`: `1`
  * `LampArrayKind`: `Notification`
  * `UpdateLatency`: `4000µs (4ms)`
  * `ColorChannels`: Red (255), Green (255), Blue (255)
* **Direct Control API:**
  ```powershell
  $lampArray.SetColor([Windows.UI.Color]::FromArgb(255, R, G, B))
  ```
  This controls the auxiliary chassis/notification status indicator directly through the Windows OS Dynamic Lighting pipeline.

---

## 7. Open Questions

These details are not yet confirmed on hardware. The `aero-rgb` tool makes each one
configurable or testable; see [HARDWARE_TESTING.md](HARDWARE_TESTING.md).

| Question | Current assumption | How to check |
| :--- | :--- | :--- |
| Which interface (`MI_00`–`MI_04`) accepts the 9-byte feature reports? | First vendor-defined usage page (`0xFF00` and up) | `aero-rgb probe --find-interface` |
| Checksum: formula (`0xEC` for cyan) or the old worked example (`0xEB`)? | Formula | `aero-rgb probe --checksum` |
| Static-mode brightness: plain value or `0x20 \| brightness`? | Plain value | `static_brightness_flag` setting |
| Are zones other than `0x01` meaningful? | Single zone (matches retail spec sheets for the AERO X16 1WH) | `aero-rgb probe --zones` |
| Does the chip save each change to permanent memory? | Unknown, so writes are rate-limited to 4 per second | Set a color and restart |
| Does the `LampArray` on `MI_04` control the keyboard or only a separate indicator? | Separate indicator | Windows Settings → Personalization → Dynamic Lighting |
