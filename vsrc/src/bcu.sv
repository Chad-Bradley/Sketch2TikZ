`ifndef __BCU_SV
`define __BCU_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module bcu import common::*; (
    input  logic [63:0] rs1_val,
    input  logic [63:0] rs2_val,
    input  br_type_t    br_type,   // 由译码阶段传入的分支类型
    output logic        br_taken   // 是否真正发生跳转
);

    always_comb begin
        case (br_type)
            BR_BEQ:  br_taken = (rs1_val == rs2_val);
            BR_BNE:  br_taken = (rs1_val != rs2_val);
            BR_BLT:  br_taken = ($signed(rs1_val) < $signed(rs2_val));
            BR_BGE:  br_taken = ($signed(rs1_val) >= $signed(rs2_val));
            BR_BLTU: br_taken = (rs1_val < rs2_val);
            BR_BGEU: br_taken = (rs1_val >= rs2_val);
            default: br_taken = 1'b0;
        endcase
    end

endmodule
`endif