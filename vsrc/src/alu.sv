`ifndef __ALU_SV
`define __ALU_SV

`ifdef VERILATOR
`include "include/common.sv"
`include "src/multiplier.sv"
`include "src/divider.sv"
`endif

module alu import common::*; (
    input  logic        clk, reset,
    input  logic [63:0] a,
    input  logic [63:0] b,
    input  alu_op_t     op,
    input  logic        is_word_op,
    input  logic        valid_in,
    output logic        ready_out,
    output logic [63:0] res
);
    // 信号分类
    logic is_mul_op, is_div_op;
    assign is_mul_op = (op == ALU_MUL || op == ALU_MULW);
    assign is_div_op = (op == ALU_DIV  || op == ALU_DIVU  || op == ALU_REM  || op == ALU_REMU ||
                        op == ALU_DIVW || op == ALU_DIVUW || op == ALU_REMW || op == ALU_REMUW);

    // 1. 简单指令运算 (纯组合逻辑)
    logic [63:0] comb_res;
    always_comb begin
        case (op)
            ALU_ADD:  comb_res = a + b;
            ALU_SUB:  comb_res = a - b;
            ALU_AND:  comb_res = a & b;
            ALU_OR:   comb_res = a | b;
            ALU_XOR:  comb_res = a ^ b;
            ALU_SLL:  comb_res = is_word_op ? (a << b[4:0]) : (a << b[5:0]);
            ALU_SRL:  comb_res = is_word_op ? (64'({a[31:0] >> b[4:0]})) : (a >> b[5:0]);
            ALU_SRA:  comb_res = is_word_op ? (64'({$signed(a[31:0]) >>> b[4:0]})) : ($signed(a) >>> b[5:0]);
            ALU_SLT:  comb_res = ($signed(a) < $signed(b)) ? 64'd1 : 64'd0;
            ALU_SLTU: comb_res = (a < b) ? 64'd1 : 64'd0;
            default:  comb_res = a + b;
        endcase
    end

    // 2. 实例化乘法器
    logic        mul_ready;
    logic [63:0] mul_res;
    multiplier mul_unit (
        .clk(clk), .reset(reset),
        .a(a), .b(b), .op(op), .is_word_op(is_word_op),
        .valid_in(valid_in && is_mul_op),
        .ready_out(mul_ready), .res(mul_res)
    );

    // 3. 实例化除法器
    logic        div_ready;
    logic [63:0] div_res;
    divider div_unit (
        .clk(clk), .reset(reset),
        .a(a), .b(b), .op(op), .is_word_op(is_word_op),
        .valid_in(valid_in && is_div_op),
        .ready_out(div_ready), .res(div_res)
    );

    // 结果汇总输出
    assign res = is_mul_op ? mul_res :
                 is_div_op ? div_res :
                 is_word_op ? {{32{comb_res[31]}}, comb_res[31:0]} : comb_res;

    assign ready_out = is_mul_op ? mul_ready :
                       is_div_op ? div_ready : 1'b1;

endmodule
`endif