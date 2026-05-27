`ifndef __REGFILE_SV
`define __REGFILE_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module regfile import common::*; (
    input  logic        clk,
    input  logic [4:0]  ra1, ra2,    
    output logic [63:0] rd1, rd2,    
    input  logic [4:0]  wa,          
    input  logic [63:0] wd,          
    input  logic        wen,  
    output logic [63:0] gpr [31:0]   
);
    logic [63:0] regs [31:0];

    // 读逻辑：组合逻辑
    assign rd1 = (ra1 == 5'b0) ? 64'b0 : (wen && (wa == ra1)) ? wd : regs[ra1];
    assign rd2 = (ra2 == 5'b0) ? 64'b0 : (wen && (wa == ra2)) ? wd : regs[ra2];

    // 写逻辑：时序逻辑
    always_ff @(posedge clk) begin
        if (wen && wa != 5'b0) begin
            regs[wa] <= wd;
        end
    end

    // 对拍专用：组合逻辑 Bypass
    // 确保 Difftest 在指令提交的那一拍就能看到更新后的寄存器值
    always_comb begin
        for (int i = 0; i < 32; i++) begin
            if (wen && wa == 5'(i) && i != 0) begin
                gpr[i] = wd;
            end else begin
                gpr[i] = regs[i];
            end
        end
    end

endmodule
`endif