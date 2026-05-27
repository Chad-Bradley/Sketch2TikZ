`ifndef __BRANCH_PREDICTOR_SV
`define __BRANCH_PREDICTOR_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module branch_predictor import common::*; (
    input  logic        clk, reset,
    
    // IF 阶段预测接口
    input  logic [63:0] pc,
    output logic        predict_taken,
    output logic [63:0] predict_target,

    // EX 阶段更新接口 (执行完毕后反馈真实结果)
    input  logic        update_en,
    input  logic [63:0] update_pc,
    input  logic        update_taken,
    input  logic [63:0] update_target
);
    // 配置：32 项 BTB (基于 PC 的 [6:2] 位索引)
    localparam BTB_AW = 5;
    localparam BTB_SIZE = 32;

    logic [63:0] btb_tags   [BTB_SIZE-1:0];
    logic [63:0] btb_targets[BTB_SIZE-1:0];
    logic [1:0]  bht_state  [BTB_SIZE-1:0];
    logic        btb_valid  [BTB_SIZE-1:0];

    logic [BTB_AW-1:0] read_idx;
    logic [BTB_AW-1:0] write_idx;

    assign read_idx  = pc[BTB_AW+1:2];
    assign write_idx = update_pc[BTB_AW+1:2];

    // 1. 预测逻辑 (组合逻辑，立即输出)
    logic hit;
    assign hit = btb_valid[read_idx] && (btb_tags[read_idx] == pc);
    // 状态 10(弱跳) 和 11(强跳) 均预测为跳转
    assign predict_taken  = hit && (bht_state[read_idx][1] == 1'b1); 
    assign predict_target = btb_targets[read_idx];

    // 2. 更新逻辑 (时序逻辑，在 EX 阶段写回)
    always_ff @(posedge clk) begin
        if (reset) begin
            for (int i=0; i<BTB_SIZE; i++) begin
                btb_valid[i] <= 1'b0;
                bht_state[i] <= 2'b00; // 默认：强烈不跳转
            end
        end else if (update_en) begin
            btb_valid[write_idx]   <= 1'b1;
            btb_tags[write_idx]    <= update_pc;
            
            // [修复点]：只有真正发生跳转时，才更新 BTB 目标地址！
            if (update_taken) begin
                btb_targets[write_idx] <= update_target;
            end

            // 2-bit 饱和计数器状态更新
            if (update_taken) begin
                if (bht_state[write_idx] != 2'b11)
                    bht_state[write_idx] <= bht_state[write_idx] + 1;
            end else begin
                if (bht_state[write_idx] != 2'b00)
                    bht_state[write_idx] <= bht_state[write_idx] - 1;
            end
        end
    end
endmodule
`endif