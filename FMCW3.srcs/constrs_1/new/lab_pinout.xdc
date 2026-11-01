#============================================================
# FMCW3 lab mode pinout - 达芬奇Pro A7 (XC7A35T-FGG484)
# 只保留：sysclk / reset_n / led1 / USB(FT232H)
#============================================================

# ---- clocks ----
create_clock -period 20.000  -name sysclk     [get_ports sysclk]        ;# 50 MHz
create_clock -period 16.667  -name usb_clkout [get_ports usb_clkout]    ;# 60 MHz (FT232H)

# ---- system clock / reset / LED ----
set_property -dict { PACKAGE_PIN R4  IOSTANDARD LVCMOS15 } [get_ports sysclk]
set_property -dict { PACKAGE_PIN U7  IOSTANDARD LVCMOS15 } [get_ports reset_n]
set_property -dict { PACKAGE_PIN V9  IOSTANDARD LVCMOS15 } [get_ports led1]

# ---- USB (FT232H sync FIFO) ----
set_property -dict { PACKAGE_PIN C17 IOSTANDARD LVCMOS33 } [get_ports {usb_data[0]}]
set_property -dict { PACKAGE_PIN F15 IOSTANDARD LVCMOS33 } [get_ports {usb_data[1]}]
set_property -dict { PACKAGE_PIN F18 IOSTANDARD LVCMOS33 } [get_ports {usb_data[2]}]
set_property -dict { PACKAGE_PIN E18 IOSTANDARD LVCMOS33 } [get_ports {usb_data[3]}]
set_property -dict { PACKAGE_PIN E21 IOSTANDARD LVCMOS33 } [get_ports {usb_data[4]}]
set_property -dict { PACKAGE_PIN D21 IOSTANDARD LVCMOS33 } [get_ports {usb_data[5]}]
set_property -dict { PACKAGE_PIN F21 IOSTANDARD LVCMOS33 } [get_ports {usb_data[6]}]
set_property -dict { PACKAGE_PIN E22 IOSTANDARD LVCMOS33 } [get_ports {usb_data[7]}]

set_property -dict { PACKAGE_PIN F16 IOSTANDARD LVCMOS33 } [get_ports usb_rxf]
set_property -dict { PACKAGE_PIN E17 IOSTANDARD LVCMOS33 } [get_ports usb_txe]
set_property -dict { PACKAGE_PIN F19 IOSTANDARD LVCMOS33 } [get_ports usb_rd]
set_property -dict { PACKAGE_PIN F20 IOSTANDARD LVCMOS33 } [get_ports usb_wr]
set_property -dict { PACKAGE_PIN D19 IOSTANDARD LVCMOS33 } [get_ports usb_oe]
set_property -dict { PACKAGE_PIN G21 IOSTANDARD LVCMOS33 } [get_ports usb_siwua]
set_property -dict { PACKAGE_PIN E19 IOSTANDARD LVCMOS33 } [get_ports usb_clkout]