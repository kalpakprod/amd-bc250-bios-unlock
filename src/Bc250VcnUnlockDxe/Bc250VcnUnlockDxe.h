/** @file
  Bc250VcnUnlockDxe.h

  Header definitions for AMD BC-250 Pre-OS VCN Enablement DXE Driver.
**/

#ifndef BC250_VCN_UNLOCK_DXE_H_
#define BC250_VCN_UNLOCK_DXE_H_

#include <Uefi.h>
#include <Guid/EventGroup.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/IoLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PciSegmentLib.h>
#include <Library/PrintLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiDriverEntryPoint.h>
#include <Library/UefiLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>

#define BC250_VCN_UNLOCK_PROTOCOL_GUID \
  { 0x5a183e20, 0x4f92, 0x4c91, { 0x88, 0x1b, 0xb6, 0x25, 0x07, 0x80, 0x13, 0xfe } }

extern EFI_GUID gBc250VcnUnlockProtocolGuid;

#define BC250_HOST_PCI_SEGMENT 0
#define BC250_HOST_PCI_BUS     0
#define BC250_HOST_PCI_DEVICE  0
#define BC250_HOST_PCI_FUNCTION 0

#define SMN_INDEX_OFFSET 0xB8
#define SMN_DATA_OFFSET  0xBC

#define BC250_PCI_SEGMENT_ADDRESS(Offset) \
  PCI_SEGMENT_LIB_ADDRESS (BC250_HOST_PCI_SEGMENT, BC250_HOST_PCI_BUS, \
                           BC250_HOST_PCI_DEVICE, BC250_HOST_PCI_FUNCTION, (Offset))

#define BC250_GPU_PCI_ADDRESS(Offset) \
  PCI_SEGMENT_LIB_ADDRESS (0, 1, 0, 0, (Offset))

// SMU Queue Register sets
#define Q2_CMD 0x03B10528U
#define Q2_RSP 0x03B10564U
#define Q2_ARG 0x03B10998U

#define Q3_CMD 0x03B10A20U
#define Q3_RSP 0x03B10A80U
#define Q3_ARG 0x03B10A88U

#define SMU_MAILBOX_ARGS          6U
#define SMU_MAILBOX_POLL_DELAY_US 1000U
#define SMU_MAILBOX_TIMEOUT_ITERS 5000U

#define SMU_RETURN_OK               0x01U
#define SMU_RETURN_REJECTED_BUSY    0xFCU
#define SMU_RETURN_REJECTED_PREREQ  0xFDU
#define SMU_RETURN_BAD_COMMAND      0xFEU
#define SMU_RETURN_FAILED           0xFFU

// SMU Exploit Addresses (Updated for BIOS 5.00 clv / Robin 5.00)
#define RING_BASE                0x188A0U
#define RING_ENTRY_SZ            16U
#define TR_TABLE_PTR             0x197D4U
#define TR_TABLE_FAKE_RING_ENTRY (TR_TABLE_PTR - 4U)
#define FAKE_ENTRY_KEY           0x13U
#define NEW_ENTRY_KEY            0x37U
#define DBG_DISABLE              0x7B44U
#define PROBE_ADDR               0x0005A870U

// VCN / Gasket Addresses (Robin 5.00 proven)
#define THUNK_SRAM_ADDR          0x3FF00U
#define Q3_HANDLER_SLOT_32       0x7774U
#define Q3_MSG_DISPATCH_PROBE    0x32U
#define GASKET_BANK12_ENABLE     0x0900C234U
#define GASKET_BANK12_LOCK       0x0900CB80U
#define VCN_UVD_SOFT_RESET       0x0900C004U
#define VCN_GASKET_DEISOLATE     0x0001F8A4U


#define RING_CMD_TYPE(cmd, subq) (((UINT32)(cmd) << 24) | (UINT32)(subq))

typedef struct {
  UINT32 Address;
  UINT32 Value;
} GASKET_WRITE_ENTRY;

#endif // BC250_VCN_UNLOCK_DXE_H_
