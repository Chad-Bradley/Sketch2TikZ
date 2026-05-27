`ifndef __EXECUTE_SV
`define __EXECUTE_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module execute import common::*;(
    input  logic       decode_ok,
    input  word_t      rs1_val,
    input  word_t      rs2_val,
    input  alu_op_t    alu_op,
    input  logic       is_word_op,
    input  logic       reg_write,
    input  addr_t      decode_pc,
    input  logic       is_jump,
    input  logic       is_branch,
    input  u3          funct3,
    input  logic       is_csr,
    input  u2          csr_op,
    input  word_t      csr_rd,
    output word_t      ex_data,        // 写回寄存器的值（jump 时为 pc+4，否则为 ALU 结果；csr 时为新 CSR 值，由 core.sv 在 EX/MEM 寄存器处覆盖为旧值）
    output addr_t      ex_jump_target, // 跳转目标地址（ALU 结果，仅 is_jump 时有意义）
    output logic       ex_reg_write,
    output logic       branch_result
);
    word_t alu_result;
    // 实例化 ALU
    alu alu_inst(
        .a(rs1_val),
        .b(rs2_val),
        .op(alu_op),
        .is_word_op(is_word_op),
        .result(alu_result)
    );

    assign ex_jump_target = alu_result & ~64'h1;  // jalr 要求最低位清零，jal 本身已对齐，清零无害
    assign ex_reg_write   = reg_write && decode_ok;

    always_comb begin
        case (funct3)
            3'b000: branch_result = (rs1_val == rs2_val);                          // beq
            3'b001: branch_result = (rs1_val != rs2_val);                          // bne
            3'b100: branch_result = ($signed(rs1_val) < $signed(rs2_val));         // blt
            3'b101: branch_result = ($signed(rs1_val) >= $signed(rs2_val));        // bge
            3'b110: branch_result = (rs1_val < rs2_val);                           // bltu
            3'b111: branch_result = (rs1_val >= rs2_val);                          // bgeu
            default: branch_result = 1'b0;
        endcase

        ex_data = is_jump ? decode_pc + 4 : alu_result;
        if (is_csr)
            case (csr_op)
                2'b01: ex_data = rs1_val;
                2'b10: ex_data = csr_rd | rs1_val;
                2'b11: ex_data = csr_rd & ~rs1_val;
                default: ex_data = 64'h0;
            endcase
    end
    
endmodule
`endif
