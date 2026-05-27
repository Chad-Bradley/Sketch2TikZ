`ifndef __FETCH_UNIT_SV
`define __FETCH_UNIT_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module fetch_unit import common::*; (
    input  logic         clk, reset,
    
    input  logic         pc_stall,
    input  logic [63:0]  pc_current,
    
    // 来自 WB 级最高优先级的异常跳转
    input  logic         wb_jump_req,
    input  logic [63:0]  wb_jump_pc,
    
    // 来自 EX / ID 级的常规跳转
    input  logic         do_ex_flush,
    input  logic [63:0]  ex_jump_pc,
    input  logic         do_id_jump,
    input  logic [63:0]  id_jump_pc,
    
    input  logic         bp_predict_taken,
    input  logic [63:0]  bp_predict_target,
    
    output ibus_req_t    ireq,
    input  ibus_resp_t   iresp,
    
    output logic [63:0]  next_pc,
    output logic         fetch_abort,
    output logic [63:0]  if_pc,
    output logic [31:0]  if_instr,
    output logic         if_valid
);

    always_comb begin
        casez ({wb_jump_req, do_ex_flush, do_id_jump, pc_stall})
            4'b1???: next_pc = wb_jump_pc; // 顶级优先权：异常接管
            4'b01??: next_pc = ex_jump_pc;
            4'b001?: next_pc = id_jump_pc;
            4'b0001: next_pc = pc_current;
            4'b0000: next_pc = bp_predict_taken ? bp_predict_target : pc_current + 4;
            default: next_pc = pc_current;
        endcase
    end

    logic [63:0] safe_addr;
    logic        wait_for_data_ok;
    
    // 只要有强行越权跳变，当前 Fetch 全部打散作废
    assign fetch_abort = (safe_addr != pc_current);

    always_ff @(posedge clk) begin
        if (reset) begin
            safe_addr <= PCINIT;
            wait_for_data_ok <= 1'b0;
        end else begin
            if (!wait_for_data_ok) begin
                safe_addr <= next_pc;
                wait_for_data_ok <= 1'b1;
            end else if (iresp.data_ok) begin
                safe_addr <= next_pc;
                wait_for_data_ok <= 1'b1;
            end
        end
    end

    assign ireq.valid = ~reset;
    assign ireq.addr  = safe_addr;

    assign if_pc    = pc_current;
    assign if_instr = iresp.data[31:0];
    assign if_valid = iresp.data_ok && !reset && !fetch_abort;

endmodule
`endif