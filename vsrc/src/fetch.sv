`ifndef __FETCH_SV
`define __FETCH_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module fetch import common::*;(
    input  logic       clk, rst,
    input  logic       stall,
    input  logic       pc_src,
    input  word_t      pc_target,
    output ibus_req_t  ireq,
    input  ibus_resp_t iresp,
    output addr_t      pc,
    output u32         instr,
    output logic       fetch_ok
);
    addr_t pc_reg;
    logic  fetch_valid;
    u32    instr_reg;
    logic  instr_ready;    // 是否有有效指令缓存在寄存器中
    logic  pending_flush;  // flush 时有 in-flight 请求未响应，需等 stale 响应后再切换地址
    addr_t pending_target; // flush 目标地址
    logic  fetch_resp_ok;
    // 收到有效响应：fetch_valid=1 且内存确认，且不是等待 stale 响应期间
    assign fetch_resp_ok = fetch_valid && iresp.data_ok && iresp.addr_ok && !pending_flush;

    always_ff @(posedge clk) begin
        if (rst) begin
            pc_reg         <= PCINIT;
            fetch_valid    <= 1'b1;
            instr_reg      <= 32'h0;
            instr_ready    <= 1'b0;
            pending_flush  <= 1'b0;
            pending_target <= '0;
        end else if (pending_flush) begin
            // 等待 stale 响应到来后再切换地址，ireq 保持不变（满足 CBus 协议）
            if (iresp.data_ok && iresp.addr_ok) begin
                // stale 响应到来，丢弃，切换到目标地址
                pending_flush <= 1'b0;
                pc_reg        <= pending_target;
                instr_ready   <= 1'b0;
                // fetch_valid 保持 1，下个周期立即取 pending_target
            end
        end else if (pc_src) begin
            // flush 请求
            instr_ready <= 1'b0;
            if (fetch_valid && !(iresp.data_ok && iresp.addr_ok)) begin
                // 有 in-flight 请求且本周期无响应：必须等 stale 响应后再切换地址
                pending_flush  <= 1'b1;
                pending_target <= pc_target;
                // ireq 保持不变（pc_reg 和 fetch_valid 不动），满足 CBus 协议
            end else begin
                // 无 in-flight 请求（fetch_valid=0）或响应恰好本周期到达：可立即切换
                pc_reg      <= pc_target;
                fetch_valid <= 1'b1;
            end
        end else begin
            // 正常操作
            if (fetch_resp_ok) begin
                if (!stall) begin
                    // 流水线可推进，直接推进 pc，fetch_valid 保持 1 继续取下一条指令
                    pc_reg <= pc_reg + 4;
                end else begin
                    // 流水线被 stall，缓存指令，停止发送请求
                    instr_reg   <= iresp.data;
                    instr_ready <= 1'b1;
                    fetch_valid <= 1'b0;
                end
            end

            // stall 解除后消费缓存指令
            if (!stall && instr_ready) begin
                instr_ready <= 1'b0;
                fetch_valid <= 1'b1;
                pc_reg      <= pc_reg + 4;
            end
        end
    end

    assign fetch_ok   = fetch_resp_ok || instr_ready;
    assign instr      = fetch_resp_ok ? iresp.data : instr_reg;  // 寄存器中有有效指令时使用，否则使用实时值
    assign pc         = pc_reg;
    assign ireq.valid = fetch_valid;  // 始终保持，不在 in-flight 期间降低，满足 CBus 协议
    assign ireq.addr  = pc_reg;

endmodule
`endif
