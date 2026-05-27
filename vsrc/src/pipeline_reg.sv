`ifndef __PIPLINE_REG_SV
`define __PIPLINE_REG_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module pipeline_reg #(
    parameter WIDTH = 64             // 通过参数控制这一级要传多少 bit 数据
)(
    input  logic              clk, reset,
    input  logic              stall, // 暂停：为 1 时保持输出不变
    input  logic              flush, // 清空：为 1 时输出清零 (气泡)
    input  logic [WIDTH-1:0]  data_in,
    output logic [WIDTH-1:0]  data_out
);
    always_ff @(posedge clk) begin
        if (reset || flush) 
            data_out <= '0;
        else if (!stall)
            data_out <= data_in;
    end
endmodule
`endif