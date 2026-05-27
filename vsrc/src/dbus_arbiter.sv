`ifndef __DBUS_ARBITER_SV
`define __DBUS_ARBITER_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module dbus_arbiter import common::*; (
    input  logic clk, reset,

    // 取指端口 (IBUS 转换为 DBUS 规格)
    input  ibus_req_t  if_req,
    output ibus_resp_t if_resp,

    // 访存端口
    input  dbus_req_t  lsu_req,
    output dbus_resp_t lsu_resp,

    // 联合输出给 MMU 的管道
    output dbus_req_t  mmu_req,
    input  dbus_resp_t mmu_resp
);
    logic busy;
    logic grant_lsu; // 1 为 LSU, 0 为 IF

    always_ff @(posedge clk) begin
        if (reset) begin
            busy <= 1'b0;
            grant_lsu <= 1'b0;
        end else begin
            if (!busy) begin
                if (lsu_req.valid || if_req.valid) begin
                    busy <= 1'b1;
                    grant_lsu <= lsu_req.valid; // LSU 访存具有更高优先级
                end
            end else begin
                if (mmu_resp.data_ok) begin
                    busy <= 1'b0;
                end
            end
        end
    end

    // 当前仲裁决定
    logic actual_grant_lsu;
    assign actual_grant_lsu = busy ? grant_lsu : lsu_req.valid;

    assign mmu_req.valid  = busy ? 1'b1 : (lsu_req.valid || if_req.valid);
    assign mmu_req.addr   = actual_grant_lsu ? lsu_req.addr   : if_req.addr;
    assign mmu_req.size   = actual_grant_lsu ? lsu_req.size   : MSIZE4;
    assign mmu_req.strobe = actual_grant_lsu ? lsu_req.strobe : 8'h00;
    assign mmu_req.data   = actual_grant_lsu ? lsu_req.data   : 64'b0;

    assign lsu_resp.data_ok = busy && actual_grant_lsu && mmu_resp.data_ok;
    assign lsu_resp.data    = mmu_resp.data;

    assign if_resp.data_ok  = busy && !actual_grant_lsu && mmu_resp.data_ok;
    // 若 addr[2] 为 1，说明指令在 64 位总线的高 32 位，需将其移至低位
    assign if_resp.data     = if_req.addr[2] ? mmu_resp.data[63:32] : mmu_resp.data[31:0];
endmodule
`endif