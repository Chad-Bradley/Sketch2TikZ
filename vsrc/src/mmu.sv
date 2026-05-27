`ifndef __MMU_SV
`define __MMU_SV

`ifdef VERILATOR
`include "include/common.sv"
`include "include/csr.sv"
`endif

module mmu import common::*, csr_pkg::*; (
    input  logic clk, reset,
    
    // CPU 状态
    input  logic [63:0] satp_val,
    input  logic [1:0]  priv_mode,

    // 来自 Arbiter 的统合输入请求
    input  dbus_req_t  mmu_in_req,
    output dbus_resp_t mmu_in_resp,

    // 向外连接 CBUS / 真实内存
    output dbus_req_t  mmu_out_req,
    input  dbus_resp_t mmu_out_resp
);
    satp_t satp;
    assign satp = satp_t'(satp_val);

    // 1. 获取实时的 MMU 使能条件
    logic mmu_enable_raw;
    assign mmu_enable_raw = (satp.mode == 4'h8) && (priv_mode != 2'b11);

    // 2. 状态锁：用于记录当前是否有总线事务正在进行
    logic transaction_active;
    logic active_mmu_enable;

    always_ff @(posedge clk) begin
        if (reset) begin
            transaction_active <= 1'b0;
            active_mmu_enable  <= 1'b0;
        end else begin
            // 当总线空闲且新请求到来时，锁死当前的 mmu_enable 状态
            if (!transaction_active && mmu_in_req.valid) begin
                transaction_active <= 1'b1;
                active_mmu_enable  <= mmu_enable_raw;
            end 
            // 当收到 data_ok，代表这笔事务完整结束，释放锁定
            else if (transaction_active && mmu_in_resp.data_ok) begin
                transaction_active <= 1'b0;
            end
        end
    end

    // 3. 最终输出：事务进行中时使用被锁定的状态，否则使用实时状态
    logic mmu_enable;
    assign mmu_enable = transaction_active ? active_mmu_enable : mmu_enable_raw;

    typedef enum logic [2:0] {
        IDLE, PTW_L2, PTW_L1, PTW_L0, TRANSLATED
    } mmu_state_t;

    mmu_state_t state;
    logic [63:0] pte_base;
    logic [63:0] phys_addr;

    logic [8:0] vpn [2:0];
    assign vpn[2] = mmu_in_req.addr[38:30];
    assign vpn[1] = mmu_in_req.addr[29:21];
    assign vpn[0] = mmu_in_req.addr[20:12];
    logic [11:0] page_offset;
    assign page_offset = mmu_in_req.addr[11:0];

    always_ff @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            pte_base <= 64'b0;
            phys_addr <= 64'b0;
        end else begin
            case (state)
                IDLE: begin
                    if (mmu_in_req.valid && mmu_enable) begin
                        state <= PTW_L2;
                        pte_base <= {8'b0, satp.ppn, 12'b0};
                    end
                end
                PTW_L2: begin
                    if (mmu_out_resp.data_ok) begin
                        if (mmu_out_resp.data[0] && (|mmu_out_resp.data[3:1])) begin
                            // 1GB 巨页：PPN[53:28] 提供物理基址，vaddr[29:0] 作为业内偏移
                            phys_addr <= {8'b0, mmu_out_resp.data[53:28], mmu_in_req.addr[29:0]};
                            state <= TRANSLATED;
                        end else begin
                            pte_base <= {8'b0, mmu_out_resp.data[53:10], 12'b0};
                            state <= PTW_L1;
                        end
                    end
                end
                PTW_L1: begin
                    if (mmu_out_resp.data_ok) begin
                        if (mmu_out_resp.data[0] && (|mmu_out_resp.data[3:1])) begin
                            // 2MB 巨页：PPN[53:19] 提供物理基址，vaddr[20:0] 作为业内偏移
                            phys_addr <= {8'b0, mmu_out_resp.data[53:19], mmu_in_req.addr[20:0]};
                            state <= TRANSLATED;
                        end else begin
                            pte_base <= {8'b0, mmu_out_resp.data[53:10], 12'b0};
                            state <= PTW_L0;
                        end
                    end
                end
                PTW_L0: begin
                    if (mmu_out_resp.data_ok) begin
                        phys_addr <= {8'b0, mmu_out_resp.data[53:10], page_offset};
                        state <= TRANSLATED;
                    end
                end
                TRANSLATED: begin
                    if (mmu_out_resp.data_ok) begin
                        state <= IDLE;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end

    // MUX 至物理层的 Request
    always_comb begin
        if (!mmu_enable) begin
            // BARE 模式：完美透传
            mmu_out_req = mmu_in_req;
            mmu_in_resp = mmu_out_resp;
        end else begin
            // 默认阻断
            mmu_out_req.valid  = 1'b0;
            mmu_out_req.addr   = 64'b0;
            mmu_out_req.size   = MSIZE8;
            mmu_out_req.strobe = 8'h00;
            mmu_out_req.data   = 64'b0;
            mmu_in_resp.data_ok= 1'b0;
            mmu_in_resp.data   = mmu_out_resp.data;

            case (state)
                PTW_L2: begin
                    mmu_out_req.valid = 1'b1;
                    mmu_out_req.addr  = pte_base + {52'b0, vpn[2], 3'b000};
                end
                PTW_L1: begin
                    mmu_out_req.valid = 1'b1;
                    mmu_out_req.addr  = pte_base + {52'b0, vpn[1], 3'b000};
                end
                PTW_L0: begin
                    mmu_out_req.valid = 1'b1;
                    mmu_out_req.addr  = pte_base + {52'b0, vpn[0], 3'b000};
                end
                TRANSLATED: begin
                    mmu_out_req.valid  = 1'b1;
                    mmu_out_req.addr   = phys_addr;
                    mmu_out_req.size   = mmu_in_req.size;
                    mmu_out_req.strobe = mmu_in_req.strobe;
                    mmu_out_req.data   = mmu_in_req.data;
                    mmu_in_resp.data_ok= mmu_out_resp.data_ok;
                end
                default: ;
            endcase
        end
    end
endmodule
`endif