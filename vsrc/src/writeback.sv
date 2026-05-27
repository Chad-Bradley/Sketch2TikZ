`ifndef __WRITEBACK_SV
`define __WRITEBACK_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module writeback import common::*;(
    input  logic       clk, rst,
    input  logic       mem_ok,
    input  word_t      mem_data,
    input  logic       mem_reg_write,
    input  creg_addr_t mem_rd,
    output logic       we3,
    output creg_addr_t wa3,
    output word_t      wd3
);
    // 写回 regfile
    assign we3 = mem_reg_write && mem_ok;
    assign wa3 = mem_rd;
    assign wd3 = mem_data;

endmodule
`endif
