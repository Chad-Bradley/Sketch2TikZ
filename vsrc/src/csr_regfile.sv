`ifndef __CSR_REGFILE_SV
`define __CSR_REGFILE_SV

`ifdef VERILATOR
`include "include/common.sv"
`include "include/csr.sv"
`endif

module csr_regfile import common::*, csr_pkg::*; (
    input  logic        clk, reset,
    
    // EX 级读端口
    input  logic [11:0] ra,
    output logic [63:0] rd_val,
    
    // WB 级写端口
    input  logic        we,
    input  logic [11:0] wa,
    input  logic [63:0] wd,
    
    // 异常与特权流转信号
    input  logic        wb_is_mret,
    input  logic        wb_is_ecall,
    input  logic        wb_is_sret,
    input  logic [63:0] wb_pc,
    output logic [1:0]  priv_mode,
    output logic [63:0] trap_target,
    
    // Difftest 探针
    output logic [63:0] csr_mstatus, csr_mtvec, csr_mip, csr_mie, 
    output logic [63:0] csr_mscratch, csr_mcause, csr_mtval, csr_mepc, 
    output logic [63:0] csr_mcycle, csr_mhartid, csr_satp,
    output logic [63:0] csr_medeleg, csr_mideleg,
    output logic [63:0] csr_stvec, csr_sscratch, csr_sepc, csr_scause, csr_stval
);

    mstatus_t mstatus_reg;
    satp_t    satp_reg;
    logic [63:0] mtvec, mip, mie, mscratch, mcause, mtval, mepc, mcycle;
    logic [63:0] medeleg, mideleg, pmpcfg0, pmpaddr0;
    logic [63:0] stvec, sscratch, sepc, scause, stval;
    
    logic [1:0]  priv_mode_reg; 

    assign csr_mhartid = 64'b0;

    // 【位宽匹配缓冲】
    logic [63:0] mstatus_val;
    assign mstatus_val = mstatus_reg;

    // =========================================================================
    // 组合逻辑透传 (Bypass)
    // =========================================================================
    mstatus_t mstatus_trap_bypass; // 提到块外定义，避免局部静态变量引发 Latch

    logic delegate_to_s;
    assign delegate_to_s = wb_is_ecall && (
        (priv_mode_reg == 2'b00 && medeleg[8]) ||
        (priv_mode_reg == 2'b01 && medeleg[9])
    );

    always_comb begin
        mstatus_trap_bypass = mstatus_reg;

        if (delegate_to_s) begin
            // 委托到 S 模式: 写 sstatus (spp/spie/sie)
            mstatus_trap_bypass.spp  = priv_mode_reg[0];
            mstatus_trap_bypass.spie = mstatus_reg.sie;
            mstatus_trap_bypass.sie  = 1'b0;
        end else if (wb_is_ecall) begin
            // 进 M 模式: 写 mstatus (mpp/mpie/mie)
            mstatus_trap_bypass.mpp  = priv_mode_reg;
            mstatus_trap_bypass.mpie = mstatus_reg.mie;
            mstatus_trap_bypass.mie  = 1'b0;
        end else if (wb_is_sret) begin
            mstatus_trap_bypass.sie  = mstatus_reg.spie;
            mstatus_trap_bypass.spie = 1'b1;
            mstatus_trap_bypass.spp  = 1'b0;
            if ({1'b0, mstatus_trap_bypass.spp} != 2'b11) mstatus_trap_bypass.mprv = 1'b0;
        end else if (wb_is_mret) begin
            mstatus_trap_bypass.mie  = mstatus_reg.mpie;
            mstatus_trap_bypass.mpie = 1'b1;
            mstatus_trap_bypass.mpp  = 2'b00;
            if (mstatus_trap_bypass.mpp != 2'b11) mstatus_trap_bypass.mprv = 1'b0;
        end

        if (wb_is_ecall || wb_is_mret || wb_is_sret) begin
            csr_mstatus = mstatus_trap_bypass;
        end else if (we && wa == CSR_MSTATUS) begin
            csr_mstatus = (mstatus_val & ~MSTATUS_MASK) | (wd & MSTATUS_MASK);
        end else if (we && wa == CSR_SSTATUS) begin
            csr_mstatus = (mstatus_val & ~SSTATUS_MASK) | (wd & SSTATUS_MASK);
            if (csr_mstatus[33:32] != 2'b10) csr_mstatus[33:32] = 2'b10;  // WARL UXL
        end else begin
            csr_mstatus = mstatus_val;
        end
    end

    logic [63:0] ecall_cause;
    always_comb begin
        case (priv_mode_reg)
            2'b00: ecall_cause = 64'd8;
            2'b01: ecall_cause = 64'd9;
            default: ecall_cause = 64'd11;
        endcase
    end

    assign priv_mode  = delegate_to_s ? 2'b01 :                     // → S
                        wb_is_ecall  ? 2'b11 :                      // → M
                        wb_is_sret   ? {1'b0, mstatus_reg.spp} :    // S→U/S
                        wb_is_mret   ? mstatus_reg.mpp : priv_mode_reg;

    assign csr_mepc   = (wb_is_ecall && !delegate_to_s) ? wb_pc :
                        (we && wa == CSR_MEPC) ? wd : mepc;
    assign csr_sepc   = (delegate_to_s) ? wb_pc :
                        (we && wa == CSR_SEPC)  ? wd : sepc;

    assign csr_mcause = (wb_is_ecall && !delegate_to_s) ? ecall_cause :
                        (we && wa == CSR_MCAUSE) ? wd : mcause;
    assign csr_scause = (delegate_to_s) ? ecall_cause :
                        (we && wa == CSR_SCAUSE) ? wd : scause;

    assign csr_stval  = (we && wa == CSR_STVAL)  ? wd : stval;
    assign csr_mtval  = (we && wa == CSR_MTVAL)  ? wd : mtval;

    assign trap_target = wb_is_sret  ? csr_sepc  :
                         wb_is_mret  ? csr_mepc  :
                         wb_is_ecall ? (delegate_to_s ? csr_stvec : csr_mtvec) :
                         64'b0;
    
    assign csr_mtvec  = (we && wa == CSR_MTVEC)  ? (wd & MTVEC_MASK) : mtvec;
    assign csr_mip    = (we && wa == CSR_MIP)    ? ((mip & ~MIP_MASK) | (wd & MIP_MASK)) : mip;
    assign csr_medeleg= (we && wa == CSR_MEDELEG)? (wd & MEDELEG_MASK) : medeleg;
    assign csr_mideleg= (we && wa == CSR_MIDELEG)? (wd & MIDELEG_MASK) : mideleg;

    assign csr_mie    = (we && wa == CSR_MIE)    ? wd : mie;
    assign csr_mscratch = (we && wa == CSR_MSCRATCH) ? wd : mscratch;
    assign csr_satp   = (we && wa == CSR_SATP)   ? wd : satp_reg;

    assign csr_stvec  = (we && wa == CSR_STVEC)  ? wd : stvec;
    assign csr_sscratch = (we && wa == CSR_SSCRATCH) ? wd : sscratch;

    // =========================================================================
    // EX 级读端口
    // =========================================================================
    always_comb begin
        case (ra)
            CSR_MSTATUS:  rd_val = mstatus_val;
            CSR_MTVEC:    rd_val = mtvec;
            CSR_MIP:      rd_val = mip;
            CSR_MIE:      rd_val = mie;
            CSR_MSCRATCH: rd_val = mscratch;
            CSR_MCAUSE:   rd_val = mcause;
            CSR_MTVAL:    rd_val = mtval;
            CSR_MEPC:     rd_val = mepc;
            CSR_MCYCLE:   rd_val = mcycle;
            CSR_MHARTID:  rd_val = csr_mhartid;
            CSR_SATP:     rd_val = satp_reg;
            CSR_MEDELEG:  rd_val = medeleg;
            CSR_MIDELEG:  rd_val = mideleg;
            CSR_PMPADDR0: rd_val = pmpaddr0;
            CSR_PMPCFG0:  rd_val = pmpcfg0;
            
            CSR_SSTATUS:  rd_val = mstatus_val & SSTATUS_MASK;
            CSR_STVEC:    rd_val = stvec;
            CSR_SIP:      rd_val = mip & mideleg; 
            CSR_SIE:      rd_val = mie & mideleg;
            CSR_SSCRATCH: rd_val = sscratch;
            CSR_SCAUSE:   rd_val = scause;
            CSR_STVAL:    rd_val = stval;
            CSR_SEPC:     rd_val = sepc;
            default:      rd_val = 64'b0;
        endcase
    end

    // =========================================================================
    // 物理寄存器时序写入逻辑
    // =========================================================================
    always_ff @(posedge clk) begin
        if (reset) begin
            priv_mode_reg <= 2'b11; 
            mstatus_reg   <= '0;
            mstatus_reg.uxl <= 2'b10;
            mstatus_reg.sxl <= 2'b10;
            satp_reg      <= '0;
            mtvec         <= 64'b0; mip <= 64'b0; mie <= 64'b0;
            mscratch      <= 64'b0; mcause <= 64'b0; mtval <= 64'b0;
            mepc          <= 64'b0; mcycle <= 64'b0; 
            medeleg       <= 64'b0; mideleg <= 64'b0;
            pmpcfg0       <= 64'b0; pmpaddr0 <= 64'b0;
            stvec         <= 64'b0; sscratch <= 64'b0; sepc <= 64'b0;
            scause        <= 64'b0; stval <= 64'b0;
        end else begin
            mcycle <= mcycle + 1; 

            if (delegate_to_s) begin
                // 委托到 S 模式: 保存现场到 S 模式 CSR
                priv_mode_reg    <= 2'b01;
                sepc             <= wb_pc;
                scause           <= ecall_cause;
                mstatus_reg.spp  <= priv_mode_reg[0];
                mstatus_reg.spie <= mstatus_reg.sie;
                mstatus_reg.sie  <= 1'b0;
            end else if (wb_is_ecall) begin
                // 进 M 模式: 保存现场到 M 模式 CSR
                mstatus_reg.mpp  <= priv_mode_reg;
                mstatus_reg.mpie <= mstatus_reg.mie;
                mstatus_reg.mie  <= 1'b0;
                priv_mode_reg    <= 2'b11;
                mepc             <= wb_pc;
                mcause           <= ecall_cause;
            end else if (wb_is_sret) begin
                priv_mode_reg    <= {1'b0, mstatus_reg.spp};
                mstatus_reg.sie  <= mstatus_reg.spie;
                mstatus_reg.spie <= 1'b1;
                mstatus_reg.spp  <= 1'b0;
                if ({1'b0, mstatus_reg.spp} != 2'b11) mstatus_reg.mprv <= 1'b0;
            end else if (wb_is_mret) begin
                priv_mode_reg    <= mstatus_reg.mpp;
                mstatus_reg.mie  <= mstatus_reg.mpie;
                mstatus_reg.mpie <= 1'b1;
                mstatus_reg.mpp  <= 2'b00;
                if (mstatus_reg.mpp != 2'b11) mstatus_reg.mprv <= 1'b0;
            end else if (we) begin
                case (wa)
                    CSR_MSTATUS:  mstatus_reg <= mstatus_t'((mstatus_val & ~MSTATUS_MASK) | (wd & MSTATUS_MASK));
                    CSR_MTVEC:    mtvec    <= wd & MTVEC_MASK;
                    CSR_MIP:      mip      <= wd & MIP_MASK;
                    CSR_MIE:      mie      <= wd;
                    CSR_MSCRATCH: mscratch <= wd;
                    CSR_MCAUSE:   mcause   <= wd;
                    CSR_MTVAL:    mtval    <= wd;
                    CSR_MEPC:     mepc     <= wd;
                    CSR_MCYCLE:   mcycle   <= wd; 
                    CSR_SATP:     satp_reg <= satp_t'(wd);
                    
                    CSR_MEDELEG:  medeleg  <= wd & MEDELEG_MASK;
                    CSR_MIDELEG:  mideleg  <= wd & MIDELEG_MASK;
                    CSR_PMPADDR0: pmpaddr0 <= wd;
                    CSR_PMPCFG0:  pmpcfg0  <= wd;
                    
                    CSR_SSTATUS: begin
                        logic [63:0] _new = (mstatus_val & ~SSTATUS_MASK) | (wd & SSTATUS_MASK);
                        if (_new[33:32] != 2'b10) _new[33:32] = 2'b10;  // WARL: UXL fixed to RV64
                        mstatus_reg <= mstatus_t'(_new);
                    end
                    CSR_SIP:      mip      <= (mip & ~mideleg) | (wd & mideleg & MIP_MASK); 
                    CSR_SIE:      mie      <= (mie & ~mideleg) | (wd & mideleg);
                    
                    CSR_STVEC:    stvec    <= wd;
                    CSR_SSCRATCH: sscratch <= wd;
                    CSR_SCAUSE:   scause   <= wd;
                    CSR_STVAL:    stval    <= wd;
                    CSR_SEPC:     sepc     <= wd;
                    default:;
                endcase
            end
        end
    end
endmodule
`endif