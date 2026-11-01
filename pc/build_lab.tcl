# Rebuild the lab bitstream: fixed 1000-word frames + real TX backpressure.
# Run:  vivado -mode batch -source pc/build_lab.tcl -nojournal -log pc/build_lab.log

set proj /home/simon/myProjects/ISAC/FMCW3/FMCW3.xpr

open_project $proj
puts "PART: [get_property PART [current_project]]"
puts "TOP : [get_property top [current_fileset]]"

reset_run synth_1
reset_run impl_1

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

puts "SYNTH STATUS: [get_property STATUS [get_runs synth_1]]"
puts "IMPL  STATUS: [get_property STATUS [get_runs impl_1]]"
puts "WNS: [get_property STATS.WNS [get_runs impl_1]]"
puts "BITSTREAM: [get_property DIRECTORY [get_runs impl_1]]/top_module_lab.bit"
close_project
