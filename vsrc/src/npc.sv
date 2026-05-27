`ifndef __NPC_SV
`define __NPC_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module npc import common::*; (
    input  logic [63:0] target_pc, 
    input  logic [63:0] pc_plus_4, 
    input  logic [63:0] rs1_val,  
    input  logic [63:0] imm,       
    input  logic        is_branch,
    input  logic        is_jal,
    input  logic        is_jalr,
    input  logic        br_taken,
    
    // 新增：CSR 也视为跳转指令，强制走冲刷逻辑
    input  logic        is_csr,    
    
    input  logic        pr_taken,
    input  logic [63:0] pr_target,

    output logic [63:0] next_pc,
    output logic        flush_req
);

    // 基础加法器：仅用于计算最终跳转目标
    logic [63:0] jalr_target;
    assign jalr_target = (rs1_val + imm) & ~64'b1;

    logic real_taken;
    assign real_taken = is_jal || is_jalr || (is_branch && br_taken) ;

    always_comb begin
        if (real_taken) begin
            if (is_jalr)     next_pc = jalr_target;
            else if (is_csr) next_pc = pc_plus_4; 
            else             next_pc = target_pc;
        end else begin
            next_pc = pc_plus_4;
        end
    end

    logic [62:0] exp_rs1_c0, exp_rs1_c1;
    assign exp_rs1_c0 = pr_target[63:1] - imm[63:1];
    assign exp_rs1_c1 = pr_target[63:1] - imm[63:1] - 1'b1;

    logic jalr_carry_in;
    assign jalr_carry_in = rs1_val[0] & imm[0];

    logic [62:0] expected_rs1_high;
    assign expected_rs1_high = jalr_carry_in ? exp_rs1_c1 : exp_rs1_c0;

    logic jalr_target_mismatch;
    assign jalr_target_mismatch = (rs1_val[63:1] != expected_rs1_high);

    logic static_target_mismatch;
    assign static_target_mismatch = (target_pc != pr_target);

    logic target_err;
    assign target_err = is_jalr ? jalr_target_mismatch : static_target_mismatch;

    assign flush_req = (real_taken != pr_taken) || 
                       (real_taken && target_err) || is_csr;

endmodule
`endif