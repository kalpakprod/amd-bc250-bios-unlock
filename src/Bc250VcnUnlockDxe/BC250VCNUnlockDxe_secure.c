/** @file BC250-VCN-Unlock DXE driver — v008-secure (route B, secure reads only).

  Variant of BC250VCNUnlockDxe.c (route B). Exact diff vs that baseline:
  1. The domain-bitmap reads (step 0 and the step-0a re-verify) use the Q3
     0x2A secure read instead of the raw PCI 0xB8/0xBC window.
  2. The step-0b plan dump loop (20 raw reads, DEBUG-logging only, values
     never used for decisions) is DELETED: zero reads in its place.
  3. Nothing else changed: same sequence, same writes, same polls.

  Reason: probe3 proved on hardware that a raw 0xB8/0xBC read of the
  clock-plan/SMU register set wedges the board (banner-only screen, wedge
  before any further output), and probe4 established the rule that raw
  touches only the Q2/Q3 mailbox addresses (0x03B1xxxx, D10R-proven class).
  After this patch every PciSegmentLib touch in the driver targets a Q3
  mailbox register. Audit with: grep -n "SmnRead32 (SMN_\|SmnRead32 (VCN_\|
  SmnRead32 (PSTEP_\|SmnRead32 (EN_BLK_\|SmnRead32 (Q3" — only Q3_* must match.

  Third driver in the MeiMeiDXEv3 family (cores, SMU, now VCN). Mailbox layer is
  adapted verbatim from the hardware-proven Bc250CoreUnlockDxe.c
  (RescueMei/BC250-DXE-SMU-Core-Unlock, MIT).

  Product framing: one flashable BIOS — "прошёл — VCN работает". No exploits:
  the SMN read (q3 0x2A), write pair (q3 0x28/0x29) and the power/clock
  messages are unguarded mailbox operations on robin_5.

  ROUTE B (2026-09-24): NEVER send 0x1B. The board's clock plan is empty and
  FUN_00024594 would zero the boot-programmed controller words (0x0115F800 =
  0x0E, 0x0115F810 = 0x013C000D, the 0x3E/0x68/0x55/0x68 table) and then hang
  the ready poll 0x0115F964 forever (emulation-proven, emu-phase2-report.txt).
  Instead the driver replays the bring-up TAIL of FUN_0002A184 directly
  (evidence/firmware-audit/20260924-plan-consumers/vcn_replay_writes.json):
  gate-mode writes, the builder-tail enable (RMW |= 1 at 0x0115F808 over the
  live 0x2), the two power steps (code 0x3F, the emulation-proven value), the
  enable-block handshake, with every poll timeout-guarded.

  PROOF STATUS (do not flash from this file):
  - mailbox layer: hardware-proven (community driver, flashed and working)
  - 0x28/0x29 write pair + 0x2A read: decompile-verified + emulation-verified
  - the replayed write set: every value cross-referenced to the emu-phase2
    tracked-write dump and the FUN_0002A184/FUN_00023890 decompiles
  - live controller state (probe4l6/4l7, 2026-09-24): boot table present,
    enable bit clear, power steps never ran — the exact pre-state this
    sequence expects
  - NOT yet hardware-tested
**/

#include <Uefi.h>

#include <Library/BaseLib.h>
#include <Library/DebugLib.h>
#include <Library/PciSegmentLib.h>
#include <Library/UefiBootServicesTableLib.h>

#define BC250_HOST_PCI_SEGMENT_ADDRESS(Offset) \
  PCI_SEGMENT_LIB_ADDRESS (0, 0, 0, 0, (Offset))

#define SMN_INDEX_OFFSET  0xB8
#define SMN_DATA_OFFSET   0xBC

/* Q3 mailbox (SMN addresses, reached through the config pair). */
#define Q3_CMD  0x03B10A20U
#define Q3_RSP  0x03B10A80U
#define Q3_ARG  0x03B10A88U

/* robin_5 message opcodes (decoded 2026-09-23/24). */
#define MSG_ALIVE_TEST     0x01U  /* rsp arg = arg + 1 (the alive probe) */
#define MSG_SMN_SET_ADDR   0x28U  /* *(0x8B08) = arg */
#define MSG_SMN_WRITE      0x29U  /* *(*(0x8B08)) = arg — arbitrary 32-bit SMN write */
#define MSG_SMN_READ       0x2AU  /* rsp arg = *arg — 32-bit SMN read (probe transport) */

/* robin_5 SMU SRAM / SMN layout (runbook §1-§4, emulation-verified 2026-09-23). */
#define SMN_DOMAIN_BITMAP  0x0000CCB8U  /* bit 6 = VCN allowed (map base 0x0000CCB0+8) */
#define SMN_CLOCK_PLAN_A   0x0115D000U  /* bit-indexed plan, copy A (reader FUN_0001CD80) */
#define SMN_CLOCK_PLAN_B   0x0115D004U  /* copy B; fields = OR of both copies */
#define SMN_VCN_DESC_OFF   0x560U       /* plan bits 0x2B00..0x2C15 -> words +0x560..+0x580 */
#define SMN_VCN_DESC_WORDS 10U          /* covers bits 0x2B00..0x2C15 inclusive */

/* route-B replay windows (FUN_0002A184 tail + FUN_00023890, vcn_replay_writes.json v1) */
#define SMN_GATE_MODE_120  0x0115A320U  /* &= ~2   (gate release 2) */
#define SMN_GATE_MODE_134  0x0115A334U  /* |= 0x30 */
#define SMN_GATE_MODE_130  0x0115A330U  /* = (r & ~0xE) | 1 */
#define SMN_GATE_MODE_12C  0x0115A32CU  /* = (r & ~7) | 0x17 */
#define SMN_GATE_MODE_138  0x0115A338U  /* |= 1 */
#define VCN_CTL_200        0x0115F800U  /* boot config 0x0E — NEVER written by route B */
#define VCN_CTL_208_EN     0x0115F808U  /* RMW |= 1 (live 0x2 -> 0x3): the PLL enable */
#define VCN_CTL_218        0x0115F818U  /* = 1 (trigger) */
#define VCN_CTL_358        0x0115F958U  /* = 0x00010000 (PTR_DAT_00017560) */
#define VCN_CTL_35C        0x0115F95CU  /* |= 0x0004C000 (DAT_000178c8) */
#define VCN_CTL_374        0x0115F974U  /* = 0 */
#define VCN_READY_POLL     0x0115F964U  /* & 0x100: PLL ready */
#define PSTEP_19_WRITE     0x0115F8FCU  /* = 0x3F (power step idx 25, emu value) */
#define PSTEP_19_ACK       0x0115F920U  /* & 0x10000: step done */
#define PSTEP_1A_WRITE     0x0115F924U  /* = 0x3F (power step idx 26) */
#define PSTEP_1A_ACK       0x0115F948U  /* & 0x10000: step done */
#define EN_BLK_204         0x0100B004U  /* = 1 */
#define EN_BLK_208         0x0100B008U  /* = 1 */
#define EN_BLK_E0          0x0100B2E0U  /* = 0xF */
#define EN_BLK_00C         0x0100B00CU  /* = 0x75767570 (packed PTR_DAT_00017fac/0x17fb0) */
#define EN_BLK_034         0x0100B034U  /* RMW |= 1, then poll bit 2 (FUN_0002a2f4) */
#define PWR_STEP_CODE      0x3FU        /* emu-phase2: the code FUN_00023a64 wrote at 0x0115F8FC */

#define MAILBOX_TIMEOUT_US  5000000U
#define MAILBOX_POLL_DELAY_US  2000U
/* 5 s / 2 ms poll step */
#define MAILBOX_TIMEOUT_LOOPS  (MAILBOX_TIMEOUT_US / MAILBOX_POLL_DELAY_US)
/* register-ready polls: 250 ms / 2 ms step (hardware polls, not mailbox waits) */
#define REG_POLL_TIMEOUT_LOOPS  125U

STATIC
UINT32
SmnRead32 (IN UINT32 Register)
{
  PciSegmentWrite32 (BC250_HOST_PCI_SEGMENT_ADDRESS (SMN_INDEX_OFFSET), Register);
  return PciSegmentRead32 (BC250_HOST_PCI_SEGMENT_ADDRESS (SMN_DATA_OFFSET));
}

STATIC
VOID
SmnWrite32 (IN UINT32 Register, IN UINT32 Value)
{
  PciSegmentWrite32 (BC250_HOST_PCI_SEGMENT_ADDRESS (SMN_INDEX_OFFSET), Register);
  PciSegmentWrite32 (BC250_HOST_PCI_SEGMENT_ADDRESS (SMN_DATA_OFFSET), Value);
}

STATIC
BOOLEAN
IsDoneStatus (IN UINT32 Status)
{
  return (BOOLEAN)(Status == 0x01U || Status == 0xFFU ||
                   Status == 0xFEU || Status == 0xFDU || Status == 0xFCU);
}

STATIC
EFI_STATUS
WaitForDoneStatus (OUT UINT32 *Status)
{
  UINT32  Value;

  for (UINT32 Attempt = 0; Attempt < MAILBOX_TIMEOUT_LOOPS; Attempt++) {
    Value = SmnRead32 (Q3_RSP);
    if (IsDoneStatus (Value)) {
      *Status = Value;
      return EFI_SUCCESS;
    }

    gBS->Stall (MAILBOX_POLL_DELAY_US);
  }

  *Status = SmnRead32 (Q3_RSP);
  return EFI_TIMEOUT;
}

STATIC
EFI_STATUS
SendQ3 (IN UINT32 Message, IN UINT32 Arg1, IN UINT32 Arg2, OUT UINT32 *Status)
{
  EFI_STATUS  Result;

  Result = WaitForDoneStatus (Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: mailbox not idle, rsp=0x%08x\n", *Status));
    return Result;
  }

  SmnWrite32 (Q3_RSP, 0);
  SmnWrite32 (Q3_ARG, Arg1);
  SmnWrite32 (Q3_ARG + sizeof (UINT32), Arg2);
  SmnWrite32 (Q3_CMD, Message);

  Result = WaitForDoneStatus (Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: msg 0x%02x timed out\n", Message));
  }

  return Result;
}

/* Arbitrary 32-bit SMN write via the unguarded 0x28/0x29 pair (robin_5). */
STATIC
EFI_STATUS
SmnSecureWrite32 (IN UINT32 SmnAddress, IN UINT32 Value, OUT UINT32 *Status)
{
  EFI_STATUS  Result;

  Result = SendQ3 (MSG_SMN_SET_ADDR, SmnAddress, 0, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  return SendQ3 (MSG_SMN_WRITE, Value, 0, Status);
}

/* 32-bit SMN read via the 0x2A mem64 window (the probe transport; the
   response value lands in the arg slot after the done status). */
STATIC
EFI_STATUS
SmnSecureRead32 (IN UINT32 SmnAddress, OUT UINT32 *Value, OUT UINT32 *Status)
{
  EFI_STATUS  Result;

  Result = SendQ3 (MSG_SMN_READ, SmnAddress, 0, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  *Value = SmnRead32 (Q3_ARG);
  return EFI_SUCCESS;
}

/* Read-modify-write through the secure pair, with readback verification. */
STATIC
EFI_STATUS
SmnSecureRmw32 (
  IN UINT32  SmnAddress,
  IN UINT32  KeepMask,
  IN UINT32  OrValue,
  OUT UINT32 *NewValue,
  OUT UINT32 *Status
  )
{
  EFI_STATUS  Result;
  UINT32      Old;
  UINT32      New;
  UINT32      Check;

  Result = SmnSecureRead32 (SmnAddress, &Old, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  New = (Old & KeepMask) | OrValue;
  if (New == Old) {
    *NewValue = New;
    return EFI_SUCCESS;  /* already in the target state */
  }

  Result = SmnSecureWrite32 (SmnAddress, New, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnSecureRead32 (SmnAddress, &Check, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  if (Check != New) {
    DEBUG ((DEBUG_ERROR, "VCN: rmw 0x%08x verify fail: wrote 0x%08x read 0x%08x\n",
            SmnAddress, New, Check));
    return EFI_DEVICE_ERROR;
  }

  *NewValue = Check;
  return EFI_SUCCESS;
}

/* Poll a register bit through the secure read; timeout aborts (never hang). */
STATIC
EFI_STATUS
SmnPollBit32 (
  IN UINT32  SmnAddress,
  IN UINT32  Mask,
  IN BOOLEAN ExpectSet,
  OUT UINT32 *LastValue,
  OUT UINT32 *Status
  )
{
  EFI_STATUS  Result;
  UINT32      Value;

  for (UINT32 Attempt = 0; Attempt < REG_POLL_TIMEOUT_LOOPS; Attempt++) {
    Result = SmnSecureRead32 (SmnAddress, &Value, Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    if (((Value & Mask) != 0) == ExpectSet) {
      *LastValue = Value;
      return EFI_SUCCESS;
    }

    gBS->Stall (MAILBOX_POLL_DELAY_US);
  }

  DEBUG ((DEBUG_ERROR, "VCN: poll 0x%08x & 0x%08x timed out (last 0x%08x)\n",
          SmnAddress, Mask, Value));
  *LastValue = Value;
  return EFI_TIMEOUT;
}

/* SMU alive check: the 0x01 test message must echo arg + 1. */
STATIC
EFI_STATUS
SmuAlive (OUT UINT32 *Status)
{
  EFI_STATUS  Result;
  UINT32      Echo;

  Result = SendQ3 (MSG_ALIVE_TEST, 0x5EED0000U, 0, Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Echo = SmnRead32 (Q3_ARG);
  if (Echo != 0x5EED0001U) {
    return EFI_DEVICE_ERROR;
  }

  return EFI_SUCCESS;
}

/**
  VCN enable sequence — ROUTE B (direct replay of the FUN_0002A184 tail,
  vcn_replay_writes.json v1, 2026-09-24):

  step 0.  SMU alive check; read the domain bitmap and the clock plan;
  step 0a. set the VCN permission bit 6 via the 0x28/0x29 pair if clear;
  step 0b. pre-state guard: log the plan and the live controller state;
           if the PLL enable bit (0x0115F808 bit 0) is already set, the
           clock part is done — skip to the power steps;
  step R.  the replay (gate modes -> enable+trigger -> ready poll ->
           tail writes -> power steps 0x3F with ack polls -> enable block
           -> handshake -> final gate bit);
  step V.  verify: alive check + the enable bit + the ack bits.

  NEVER sends 0x1B: with the empty plan the SMU would zero the boot
  controller words and hang its own ready poll (emu-phase2 proof).
  Skipped by design (one variable per flash): the 0x01D80814 |= 2 write
  (second gate measured already open, R3), the 0x0220FE00 &= ~4 release
  (its read safety is unproven), the FUN_0002a344 table pump (identity
  unestablished).
**/
STATIC
EFI_STATUS
VcnEnableSequence (VOID)
{
  EFI_STATUS  Result;
  UINT32      Status = 0;
  UINT32      Bitmap;
  UINT32      Word;
  UINT32      i;

  /* step 0: alive + the permission bitmap */
  Result = SmuAlive (&Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: SMU not alive at entry (rsp 0x%08x)\n", Status));
    return Result;
  }

  Result = SmnSecureRead32 (SMN_DOMAIN_BITMAP, &Bitmap, &Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: bitmap secure read failed, rsp=0x%08x\n", Status));
    return Result;
  }
  DEBUG ((DEBUG_INFO, "VCN: domain bitmap 0x%08x\n", Bitmap));

  /* step 0a: VCN permission bit 6 (O3 resolved: direct 0x28/0x29 write) */
  if ((Bitmap & 0x40U) == 0) {
    Result = SmnSecureWrite32 (SMN_DOMAIN_BITMAP, Bitmap | 0x40U, &Status);
    if (EFI_ERROR (Result)) {
      DEBUG ((DEBUG_ERROR, "VCN: bitmap set failed, rsp=0x%08x\n", Status));
      return Result;
    }

    Result = SmnSecureRead32 (SMN_DOMAIN_BITMAP, &Bitmap, &Status);
    if (EFI_ERROR (Result)) {
      DEBUG ((DEBUG_ERROR, "VCN: bitmap re-verify failed, rsp=0x%08x\n", Status));
      return Result;
    }
    if ((Bitmap & 0x40U) == 0) {
      DEBUG ((DEBUG_ERROR, "VCN: bitmap bit 6 did not stick\n"));
      return EFI_DEVICE_ERROR;
    }
  }

  /* step 0b: the live controller pre-state (secure read only).
     The route-B plan dump loop (20 raw reads of 0x0115D560+) was deleted
     here: probe3 proved that address class wedges the board on a raw read,
     and the dumped values were DEBUG-logging only, never used. */
  (VOID)i;
  Result = SmnSecureRead32 (VCN_CTL_208_EN, &Word, &Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: pre-state read failed, rsp=0x%08x\n", Status));
    return Result;
  }
  DEBUG ((DEBUG_INFO, "VCN: ctl 0x0115F808 = 0x%08x (enable bit %a)\n",
          Word, (Word & 1U) != 0 ? "set" : "clear"));

  if ((Word & 1U) != 0) {
    /* clock part already done — verify the ready bit, then the power steps */
    Result = SmnPollBit32 (VCN_READY_POLL, 0x100U, TRUE, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }
  } else {
    /* step R1-R6: the gate-mode writes (FUN_0002A184 head) */
    Result = SmnSecureRmw32 (SMN_GATE_MODE_120, ~2U, 0U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    Result = SmnSecureRmw32 (SMN_GATE_MODE_134, 0xFFFFFFFFU, 0x30U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    Result = SmnSecureRmw32 (SMN_GATE_MODE_130, ~0xEU, 1U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    /* the FUN_00002b2c(10) settle delay */
    gBS->Stall (1000U);

    Result = SmnSecureRmw32 (SMN_GATE_MODE_12C, ~7U, 0x17U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    /* step R8-R9: the builder TAIL only — enable + trigger.
       NEVER write 0x0115F800/810/850.. as FUN_00024594 would (it reads
       the empty plan and zeroes the boot-programmed words). */
    Result = SmnSecureRmw32 (VCN_CTL_208_EN, 0xFFFFFFFFU, 1U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    Result = SmnSecureWrite32 (VCN_CTL_218, 1U, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    /* step R10: the PLL ready poll (timeout aborts, never hang) */
    Result = SmnPollBit32 (VCN_READY_POLL, 0x100U, TRUE, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    /* step R11-R13: the builder tail writes */
    Result = SmnSecureWrite32 (VCN_CTL_358, 0x00010000U, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    Result = SmnSecureRmw32 (VCN_CTL_35C, 0xFFFFFFFFU, 0x0004C000U, &Word, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }

    Result = SmnSecureWrite32 (VCN_CTL_374, 0U, &Status);
    if (EFI_ERROR (Result)) {
      return Result;
    }
  }

  /* step R14-R17: the power steps (FUN_00023890 for idx 25/26, code 0x3F) */
  Result = SmnSecureWrite32 (PSTEP_19_WRITE, PWR_STEP_CODE, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnPollBit32 (PSTEP_19_ACK, 0x10000U, TRUE, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnSecureWrite32 (PSTEP_1A_WRITE, PWR_STEP_CODE, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnPollBit32 (PSTEP_1A_ACK, 0x10000U, TRUE, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  /* step R18-R21: the enable block */
  Result = SmnSecureWrite32 (EN_BLK_204, 1U, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnSecureWrite32 (EN_BLK_208, 1U, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnSecureWrite32 (EN_BLK_E0, 0xFU, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnSecureWrite32 (EN_BLK_00C, 0x75767570U, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  /* step R22: the enable-block handshake (RMW |= 1, then poll bit 2) */
  Result = SmnSecureRmw32 (EN_BLK_034, 0xFFFFFFFFU, 1U, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  Result = SmnPollBit32 (EN_BLK_034, 2U, TRUE, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  /* step R23: the final gate bit */
  Result = SmnSecureRmw32 (SMN_GATE_MODE_138, 0xFFFFFFFFU, 1U, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  /* step V: verify */
  Result = SmuAlive (&Status);
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: SMU not alive after the sequence (rsp 0x%08x)\n", Status));
    return Result;
  }

  Result = SmnSecureRead32 (VCN_CTL_208_EN, &Word, &Status);
  if (EFI_ERROR (Result)) {
    return Result;
  }

  DEBUG ((DEBUG_INFO, "VCN: final ctl 0x0115F808 = 0x%08x (enable %a)\n",
          Word, (Word & 1U) != 0 ? "set" : "clear"));
  return (Word & 1U) != 0 ? EFI_SUCCESS : EFI_DEVICE_ERROR;
}

EFI_STATUS
EFIAPI
Bc250VcnUnlockDxeEntryPoint (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  DEBUG ((DEBUG_INFO, "Bc250VCNUnlock: entry (autonomous monolithic O3)\n"));

  EFI_STATUS  Result = VcnEnableSequence ();
  if (EFI_ERROR (Result)) {
    DEBUG ((DEBUG_ERROR, "VCN: sequence returned %r (non-fatal)\n", Result));
    return EFI_SUCCESS;
  }

  DEBUG ((DEBUG_INFO, "VCN: sequence complete successfully\n"));
  return EFI_SUCCESS;
}
