`ifndef __CORE_SV
`define __CORE_SV

`ifdef VERILATOR
`include "include/common.sv"
`include "include/csr.sv"
`include "src/decode.sv"
`include "src/regfile.sv"
`include "src/csr_regfile.sv"
`include "src/alu.sv"
`include "src/pipeline_reg.sv"
`include "src/lsu.sv"         
`include "src/hazard_unit.sv" 
`include "src/bcu.sv"         
`include "src/npc.sv"         
`include "src/branch_predictor.sv"
`include "src/fetch_unit.sv"
`include "src/dbus_arbiter.sv"
`include "src/mmu.sv"
`endif

module core import common::*, csr_pkg::*; (
    input  logic       clk, reset,
    output ibus_req_t  ireq,   // 已废弃，向外恒置 0
    input  logic       trint, swint, exint,
    input  ibus_resp_t iresp,
    output dbus_req_t  dreq,   // 全新总线出口，承载了 IF 和 MEM 经过 MMU 的流量
    input  dbus_resp_t dresp
);
    /* -------------------------------------------------------------------------- */
    /* 1. 流水线结构体精细拆分                                                     */
    /* -------------------------------------------------------------------------- */
    
    typedef struct packed { logic valid; logic pr_taken; } if_id_ctrl_t;
    typedef struct packed { logic [63:0] pc; logic [31:0] instr; logic [63:0] pr_target; } if_id_data_t;
    typedef struct packed { if_id_ctrl_t ctrl; if_id_data_t data; } if_id_t;

    typedef struct packed {
        logic valid; logic rf_we; logic is_trap; logic mem_re; logic mem_we;
        logic is_branch; logic is_jal; logic is_jalr; logic pr_taken;
        logic is_csr; csr_op_t csr_op; 
        logic is_mret; logic is_ecall; logic is_sret;
    } id_ex_ctrl_t;
    typedef struct packed {
        logic [63:0] pc; logic [31:0] instr; logic [4:0] rs1, rs2, rd; logic [63:0] imm;
        logic [63:0] target_pc; logic [63:0] pc_plus_4; logic [63:0] rd1, rd2;
        logic fw_a_ex_hit, fw_a_mem_hit, fw_b_ex_hit, fw_b_mem_hit;
        alu_op_t alu_op; br_type_t br_type; logic alu_src_sel; logic is_word_op; logic is_m_op;
        logic is_auipc; msize_t mem_size; logic mem_unsigned;
        logic [63:0] pr_target;
        logic [11:0] csr_addr; logic [63:0] csr_zimm; logic csr_use_imm; 
    } id_ex_data_t;
    typedef struct packed { id_ex_ctrl_t ctrl; id_ex_data_t data; } id_ex_t;

    typedef struct packed {
        logic valid; logic rf_we; logic is_trap; logic mem_re; logic mem_we;
        logic is_csr;
        logic is_mret; logic is_ecall; logic is_sret;
    } ex_mem_ctrl_t;
    typedef struct packed {
        logic [63:0] pc; logic [31:0] instr; logic [4:0] rd; logic [63:0] alu_res; 
        logic [63:0] rs2_val; logic [63:0] mem_addr; msize_t mem_size; logic mem_unsigned;
        logic [11:0] csr_addr; logic [63:0] csr_wdata; 
    } ex_mem_data_t;
    typedef struct packed { ex_mem_ctrl_t ctrl; ex_mem_data_t data; } ex_mem_t;

    typedef struct packed {
        logic valid; logic rf_we; logic is_trap; logic mem_re; logic mem_we;
        logic is_csr;
        logic is_mret; logic is_ecall; logic is_sret;
    } mem_wb_ctrl_t;
    typedef struct packed {
        logic [63:0] pc; logic [31:0] instr; logic [4:0] rd; logic [63:0] final_res; logic [63:0] mem_addr;     
        logic [11:0] csr_addr; logic [63:0] csr_wdata;
    } mem_wb_data_t;
    typedef struct packed { mem_wb_ctrl_t ctrl; mem_wb_data_t data; } mem_wb_t;

    // 内部连线
    logic [63:0] pc; logic [63:0] gpr_state [31:0];
    if_id_t  if_id_in,  if_id_out;
    id_ex_t  id_ex_in,  id_ex_out;
    ex_mem_t ex_mem_in, ex_mem_out;
    mem_wb_t mem_wb_in, mem_wb_out;
    logic alu_ready, lsu_ready; 
    logic pc_stall, if_id_stall, id_ex_stall, ex_mem_stall;
    logic if_id_flush, id_ex_flush, ex_jump_flush;
    logic [63:0] ex_jump_pc, id_jump_pc; 
    logic id_jump_req, fetch_abort;

    /* -------------------------------------------------------------------------- */
    /* 总线与 MMU 的统合封装（替代原版直接接头）                                     */
    /* -------------------------------------------------------------------------- */
    assign ireq.valid = 1'b0; // 废弃外部 ireq 端口
    assign ireq.addr  = 64'b0;

    ibus_req_t  core_ireq;  ibus_resp_t core_iresp;
    dbus_req_t  core_dreq;  dbus_resp_t core_dresp;
    dbus_req_t  arb_mmu_req; dbus_resp_t arb_mmu_resp;
    
    logic [1:0]  priv_mode;
    logic [63:0] difftest_satp;

    dbus_arbiter arbiter_unit (
        .clk(clk), .reset(reset),
        .if_req(core_ireq), .if_resp(core_iresp),
        .lsu_req(core_dreq), .lsu_resp(core_dresp),
        .mmu_req(arb_mmu_req), .mmu_resp(arb_mmu_resp)
    );

    mmu mmu_unit (
        .clk(clk), .reset(reset),
        .satp_val(difftest_satp), .priv_mode(priv_mode),
        .mmu_in_req(arb_mmu_req), .mmu_in_resp(arb_mmu_resp),
        .mmu_out_req(dreq), .mmu_out_resp(dresp) // dreq 和 dresp 直接连接 Core 最外层
    );

    /* -------------------------------------------------------------------------- */
    /* 流水线主体                                                                 */
    /* -------------------------------------------------------------------------- */
    
    // MRET/SRET/ECALL 提交级触发的全流水线冲刷控制
    logic wb_jump_req;
    logic [63:0] wb_jump_pc;
    logic [63:0] csr_trap_target;
    logic [63:0] difftest_mepc, difftest_mtvec;

    assign wb_jump_req = mem_wb_out.ctrl.valid && (mem_wb_out.ctrl.is_mret || mem_wb_out.ctrl.is_sret || mem_wb_out.ctrl.is_ecall);
    assign wb_jump_pc  = csr_trap_target;

    logic ex_stage_busy;
    assign ex_stage_busy = id_ex_out.ctrl.valid && id_ex_out.data.is_m_op && !alu_ready;

    hazard_unit hazard_ctrl (
        .if_not_ready(!core_iresp.data_ok || fetch_abort), 
        .ex_not_ready(ex_stage_busy),
        .lsu_not_ready(!lsu_ready),
        .id_ex_rd(id_ex_out.data.rd),
        .id_ex_mem_re(id_ex_out.ctrl.mem_re),
        .dec_rs1(dec_rs1), .dec_rs2(dec_rs2),
        .pc_stall(pc_stall), .if_id_stall(if_id_stall), .id_ex_stall(id_ex_stall), .ex_mem_stall(ex_mem_stall),
        .if_id_flush(if_id_flush), .id_ex_flush(id_ex_flush),
        .jump_flush(ex_jump_flush), .id_jump_req(id_jump_req),
        .wb_jump_req(wb_jump_req)
    );

    logic bp_predict_taken; logic [63:0] bp_predict_target;
    logic pipeline_ready_to_jump;
    assign pipeline_ready_to_jump = lsu_ready && !ex_stage_busy;

    logic do_ex_flush, do_id_jump;
    assign do_ex_flush = ex_jump_flush && pipeline_ready_to_jump;
    assign do_id_jump  = id_jump_req && !id_ex_stall;

    logic [63:0] next_pc;
    fetch_unit if_stage (
        .clk(clk), .reset(reset), .pc_stall(pc_stall), .pc_current(pc),
        .wb_jump_req(wb_jump_req), .wb_jump_pc(wb_jump_pc), // 新接入
        .do_ex_flush(do_ex_flush), .ex_jump_pc(ex_jump_pc), 
        .do_id_jump(do_id_jump), .id_jump_pc(id_jump_pc),
        .bp_predict_taken(bp_predict_taken), .bp_predict_target(bp_predict_target),
        .ireq(core_ireq), .iresp(core_iresp), .next_pc(next_pc), .fetch_abort(fetch_abort), // 使用 core_ireq
        .if_pc(if_id_in.data.pc), .if_instr(if_id_in.data.instr), .if_valid(if_id_in.ctrl.valid)
    );

    assign if_id_in.ctrl.pr_taken  = bp_predict_taken;
    assign if_id_in.data.pr_target = bp_predict_target;

    always_ff @(posedge clk) begin
        if (reset) pc <= PCINIT;
        else pc <= next_pc;
    end

    pipeline_reg #($bits(if_id_ctrl_t)) reg_if_id_ctrl (
        .clk(clk), .reset(reset), .stall(if_id_stall), .flush(if_id_flush),
        .data_in(if_id_in.ctrl), .data_out(if_id_out.ctrl)
    );
    pipeline_reg #($bits(if_id_data_t)) reg_if_id_data (
        .clk(clk), .reset(reset), .stall(if_id_stall), .flush(1'b0), 
        .data_in(if_id_in.data), .data_out(if_id_out.data)
    );

    logic [4:0]  dec_rs1, dec_rs2, dec_rd;
    logic [63:0] dec_imm, dec_rd1, dec_rd2;
    logic        dec_rf_we, dec_alu_src_sel, dec_is_word_op, dec_is_m_op, dec_is_trap;
    logic        dec_mem_re, dec_mem_we, dec_mem_unsigned;
    logic        dec_is_branch, dec_is_jal, dec_is_jalr, dec_is_auipc; 
    logic        dec_is_csr, dec_csr_use_imm, dec_is_mret, dec_is_ecall, dec_is_sret;
    br_type_t    dec_br_type; msize_t dec_mem_size; alu_op_t dec_alu_op; csr_op_t dec_csr_op;

    decode dec_unit (
        .instr(if_id_out.data.instr),
        .rs1(dec_rs1), .rs2(dec_rs2), .rd(dec_rd), .rf_we(dec_rf_we), .imm(dec_imm),
        .alu_op(dec_alu_op), .alu_src_sel(dec_alu_src_sel), .is_word_op(dec_is_word_op), .is_m_op(dec_is_m_op),
        .is_trap(dec_is_trap), .mem_re(dec_mem_re), .mem_we(dec_mem_we),
        .mem_size(dec_mem_size), .mem_unsigned(dec_mem_unsigned),
        .is_branch(dec_is_branch), .is_jal(dec_is_jal), .is_jalr(dec_is_jalr), .is_auipc(dec_is_auipc), .br_type(dec_br_type),
        .is_csr(dec_is_csr), .csr_op(dec_csr_op), .csr_use_imm(dec_csr_use_imm),
        .is_mret(dec_is_mret), .is_ecall(dec_is_ecall), .is_sret(dec_is_sret)
    );

    assign id_jump_req = dec_is_jal && if_id_out.ctrl.valid && !if_id_out.ctrl.pr_taken;
    assign id_jump_pc  = if_id_out.data.pc + dec_imm;

    regfile rf_unit (
        .clk(clk), .ra1(dec_rs1), .ra2(dec_rs2), .rd1(dec_rd1), .rd2(dec_rd2),
        .wa(mem_wb_out.data.rd), .wd(mem_wb_out.data.final_res), 
        .wen(mem_wb_out.ctrl.rf_we && mem_wb_out.ctrl.valid), .gpr(gpr_state)
    );

    logic id_valid;
    assign id_valid = if_id_out.ctrl.valid;
    
    assign id_ex_in.ctrl.valid     = id_valid;
    assign id_ex_in.ctrl.rf_we     = dec_rf_we     & id_valid;
    assign id_ex_in.ctrl.is_trap   = dec_is_trap   & id_valid;
    assign id_ex_in.ctrl.mem_re    = dec_mem_re    & id_valid;
    assign id_ex_in.ctrl.mem_we    = dec_mem_we    & id_valid;
    assign id_ex_in.ctrl.is_branch = dec_is_branch & id_valid;
    assign id_ex_in.ctrl.is_jal    = dec_is_jal    & id_valid;
    assign id_ex_in.ctrl.is_jalr   = dec_is_jalr   & id_valid;
    assign id_ex_in.ctrl.pr_taken  = if_id_out.ctrl.pr_taken & id_valid;
    assign id_ex_in.ctrl.is_csr    = dec_is_csr    & id_valid;
    assign id_ex_in.ctrl.csr_op    = dec_csr_op;
    assign id_ex_in.ctrl.is_mret   = dec_is_mret   & id_valid;
    assign id_ex_in.ctrl.is_ecall  = dec_is_ecall  & id_valid;
    assign id_ex_in.ctrl.is_sret   = dec_is_sret   & id_valid;

    assign id_ex_in.data.fw_a_ex_hit  = (dec_rs1 != 5'b0) && (dec_rs1 == id_ex_out.data.rd);
    assign id_ex_in.data.fw_a_mem_hit = (dec_rs1 != 5'b0) && (dec_rs1 == ex_mem_out.data.rd);
    assign id_ex_in.data.fw_b_ex_hit  = (dec_rs2 != 5'b0) && (dec_rs2 == id_ex_out.data.rd);
    assign id_ex_in.data.fw_b_mem_hit = (dec_rs2 != 5'b0) && (dec_rs2 == ex_mem_out.data.rd);

    assign id_ex_in.data.pc           = if_id_out.data.pc;
    assign id_ex_in.data.instr        = if_id_out.data.instr;
    assign id_ex_in.data.rs1          = dec_rs1;
    assign id_ex_in.data.rs2          = dec_rs2;
    assign id_ex_in.data.rd           = dec_rd;
    assign id_ex_in.data.imm          = dec_imm;
    assign id_ex_in.data.target_pc    = if_id_out.data.pc + dec_imm; 
    assign id_ex_in.data.pc_plus_4    = if_id_out.data.pc + 4;
    assign id_ex_in.data.rd1          = dec_rd1;
    assign id_ex_in.data.rd2          = dec_rd2;
    assign id_ex_in.data.alu_op       = dec_alu_op;
    assign id_ex_in.data.br_type      = dec_br_type;
    assign id_ex_in.data.alu_src_sel  = dec_alu_src_sel;
    assign id_ex_in.data.is_word_op   = dec_is_word_op;
    assign id_ex_in.data.is_m_op      = dec_is_m_op;
    assign id_ex_in.data.is_auipc     = dec_is_auipc;
    assign id_ex_in.data.mem_size     = dec_mem_size;
    assign id_ex_in.data.mem_unsigned = dec_mem_unsigned;
    assign id_ex_in.data.pr_target    = if_id_out.data.pr_target;
    assign id_ex_in.data.csr_addr     = dec_imm[11:0];
    assign id_ex_in.data.csr_zimm     = {59'b0, dec_rs1};
    assign id_ex_in.data.csr_use_imm  = dec_csr_use_imm;

    pipeline_reg #($bits(id_ex_ctrl_t)) reg_id_ex_ctrl (
        .clk(clk), .reset(reset), .stall(id_ex_stall), .flush(id_ex_flush),
        .data_in(id_ex_in.ctrl), .data_out(id_ex_out.ctrl)
    );
    pipeline_reg #($bits(id_ex_data_t)) reg_id_ex_data (
        .clk(clk), .reset(reset), .stall(id_ex_stall), .flush(1'b0), 
        .data_in(id_ex_in.data), .data_out(id_ex_out.data)
    );

    logic[63:0] forward_a, forward_b;
    logic [63:0] current_alu_res;
    logic fw_a_ex_mem, fw_a_mem_wb, fw_b_ex_mem, fw_b_mem_wb;

    assign fw_a_ex_mem = id_ex_out.data.fw_a_ex_hit  && ex_mem_out.ctrl.rf_we && ex_mem_out.ctrl.valid;
    assign fw_a_mem_wb = id_ex_out.data.fw_a_mem_hit && mem_wb_out.ctrl.rf_we && mem_wb_out.ctrl.valid;
    assign fw_b_ex_mem = id_ex_out.data.fw_b_ex_hit  && ex_mem_out.ctrl.rf_we && ex_mem_out.ctrl.valid;
    assign fw_b_mem_wb = id_ex_out.data.fw_b_mem_hit && mem_wb_out.ctrl.rf_we && mem_wb_out.ctrl.valid;

    always_comb begin
        if (fw_a_ex_mem)      forward_a = ex_mem_out.data.alu_res;
        else if (fw_a_mem_wb) forward_a = mem_wb_out.data.final_res;
        else                  forward_a = id_ex_out.data.rd1;
        
        if (fw_b_ex_mem)      forward_b = ex_mem_out.data.alu_res;
        else if (fw_b_mem_wb) forward_b = mem_wb_out.data.final_res;
        else                  forward_b = id_ex_out.data.rd2;
    end

    logic [63:0] csr_rdata;
    logic [63:0] ex_csr_operand, ex_csr_actual_wdata;
    assign ex_csr_operand = id_ex_out.data.csr_use_imm ? id_ex_out.data.csr_zimm : forward_a;

    always_comb begin
        case (id_ex_out.ctrl.csr_op)
            CSR_RW:  ex_csr_actual_wdata = ex_csr_operand;
            CSR_RS:  ex_csr_actual_wdata = csr_rdata | ex_csr_operand;
            CSR_RC:  ex_csr_actual_wdata = csr_rdata & ~ex_csr_operand;
            default: ex_csr_actual_wdata = ex_csr_operand;
        endcase
    end

    alu alu_unit (
        .clk(clk), .reset(reset),
        .a(forward_a), .b(id_ex_out.data.alu_src_sel ? id_ex_out.data.imm : forward_b),
        .op(id_ex_out.data.alu_op), .is_word_op(id_ex_out.data.is_word_op),
        .valid_in(id_ex_out.ctrl.valid), .ready_out(alu_ready), .res(current_alu_res)
    );

    logic br_taken;
    bcu bcu_unit (.rs1_val(forward_a), .rs2_val(forward_b), .br_type(id_ex_out.data.br_type), .br_taken(br_taken));

    npc npc_unit (
        .target_pc(id_ex_out.data.target_pc), .pc_plus_4(id_ex_out.data.pc_plus_4),
        .rs1_val(forward_a), .imm(id_ex_out.data.imm),             
        .is_branch(id_ex_out.ctrl.is_branch), .is_jal(id_ex_out.ctrl.is_jal), .is_jalr(id_ex_out.ctrl.is_jalr),
        .br_taken (br_taken), .is_csr(id_ex_out.ctrl.is_csr), 
        .pr_taken (id_ex_out.ctrl.pr_taken), .pr_target(id_ex_out.data.pr_target), 
        .next_pc(ex_jump_pc), .flush_req(ex_jump_flush)
    );

    logic bp_update_en, bp_update_taken;
    assign bp_update_en    = id_ex_out.ctrl.valid && (id_ex_out.ctrl.is_branch || id_ex_out.ctrl.is_jal || id_ex_out.ctrl.is_jalr);
    assign bp_update_taken = (id_ex_out.ctrl.is_branch && br_taken) || id_ex_out.ctrl.is_jal || id_ex_out.ctrl.is_jalr;

    branch_predictor bp_unit (
        .clk(clk), .reset(reset), .pc(pc),
        .predict_taken(bp_predict_taken), .predict_target(bp_predict_target),
        .update_en(bp_update_en), .update_pc(id_ex_out.data.pc),
        .update_taken(bp_update_taken), .update_target(ex_jump_pc)
    );

    logic ex_valid;
    assign ex_valid = id_ex_out.ctrl.valid && alu_ready;

    assign ex_mem_in.ctrl.valid   = ex_valid;
    assign ex_mem_in.ctrl.rf_we   = id_ex_out.ctrl.rf_we   & ex_valid;
    assign ex_mem_in.ctrl.is_trap = id_ex_out.ctrl.is_trap & ex_valid;
    assign ex_mem_in.ctrl.mem_re  = id_ex_out.ctrl.mem_re  & ex_valid;
    assign ex_mem_in.ctrl.mem_we  = id_ex_out.ctrl.mem_we  & ex_valid;
    assign ex_mem_in.ctrl.is_csr  = id_ex_out.ctrl.is_csr  & ex_valid;
    assign ex_mem_in.ctrl.is_mret = id_ex_out.ctrl.is_mret & ex_valid;
    assign ex_mem_in.ctrl.is_ecall= id_ex_out.ctrl.is_ecall& ex_valid;
    assign ex_mem_in.ctrl.is_sret = id_ex_out.ctrl.is_sret & ex_valid;

    assign ex_mem_in.data.pc      = id_ex_out.data.pc;
    assign ex_mem_in.data.instr   = id_ex_out.data.instr;
    assign ex_mem_in.data.rd      = id_ex_out.data.rd;
    always_comb begin
        if (id_ex_out.ctrl.is_csr)                           ex_mem_in.data.alu_res = csr_rdata;
        else if (id_ex_out.ctrl.is_jal || id_ex_out.ctrl.is_jalr) ex_mem_in.data.alu_res = id_ex_out.data.pc_plus_4;
        else if (id_ex_out.data.is_auipc)                    ex_mem_in.data.alu_res = id_ex_out.data.target_pc;
        else                                                 ex_mem_in.data.alu_res = current_alu_res;
    end
    assign ex_mem_in.data.rs2_val      = forward_b;
    assign ex_mem_in.data.mem_addr     = current_alu_res; 
    assign ex_mem_in.data.mem_size     = id_ex_out.data.mem_size;
    assign ex_mem_in.data.mem_unsigned = id_ex_out.data.mem_unsigned;
    assign ex_mem_in.data.csr_addr     = id_ex_out.data.csr_addr;
    assign ex_mem_in.data.csr_wdata    = ex_csr_actual_wdata;

    pipeline_reg #($bits(ex_mem_ctrl_t)) reg_ex_mem_ctrl (
        .clk(clk), .reset(reset), .stall(ex_mem_stall), .flush(wb_jump_req), // 被 WB 打断则冲刷
        .data_in(ex_mem_in.ctrl), .data_out(ex_mem_out.ctrl)
    );
    pipeline_reg #($bits(ex_mem_data_t)) reg_ex_mem_data (
        .clk(clk), .reset(reset), .stall(ex_mem_stall), .flush(1'b0), 
        .data_in(ex_mem_in.data), .data_out(ex_mem_out.data)
    );

    logic[63:0] lsu_rdata;
    lsu lsu_unit (
        .clk(clk), .reset(reset), .valid_in(ex_mem_out.ctrl.valid),
        .mem_re(ex_mem_out.ctrl.mem_re), .mem_we(ex_mem_out.ctrl.mem_we),
        .mem_size(ex_mem_out.data.mem_size), .mem_unsigned(ex_mem_out.data.mem_unsigned),
        .addr(ex_mem_out.data.alu_res), .wdata_src(ex_mem_out.data.rs2_val),
        .rdata_out(lsu_rdata), .lsu_ready(lsu_ready), .dreq(core_dreq), .dresp(core_dresp) // 使用 core_dreq
    );

    logic mem_valid;
    assign mem_valid = ex_mem_out.ctrl.valid && lsu_ready;
    
    assign mem_wb_in.ctrl.valid   = mem_valid;
    assign mem_wb_in.ctrl.rf_we   = ex_mem_out.ctrl.rf_we   & mem_valid;
    assign mem_wb_in.ctrl.is_trap = ex_mem_out.ctrl.is_trap & mem_valid;
    assign mem_wb_in.ctrl.mem_re  = ex_mem_out.ctrl.mem_re  & mem_valid;
    assign mem_wb_in.ctrl.mem_we  = ex_mem_out.ctrl.mem_we  & mem_valid;
    assign mem_wb_in.ctrl.is_csr  = ex_mem_out.ctrl.is_csr  & mem_valid;
    assign mem_wb_in.ctrl.is_mret = ex_mem_out.ctrl.is_mret & mem_valid;
    assign mem_wb_in.ctrl.is_ecall= ex_mem_out.ctrl.is_ecall& mem_valid;
    assign mem_wb_in.ctrl.is_sret = ex_mem_out.ctrl.is_sret & mem_valid;
    
    assign mem_wb_in.data.pc        = ex_mem_out.data.pc;
    assign mem_wb_in.data.instr     = ex_mem_out.data.instr;
    assign mem_wb_in.data.rd        = ex_mem_out.data.rd;
    assign mem_wb_in.data.final_res = ex_mem_out.ctrl.mem_re ? lsu_rdata : ex_mem_out.data.alu_res;
    assign mem_wb_in.data.mem_addr  = ex_mem_out.data.mem_addr; 
    assign mem_wb_in.data.csr_addr  = ex_mem_out.data.csr_addr;
    assign mem_wb_in.data.csr_wdata = ex_mem_out.data.csr_wdata;

    pipeline_reg #($bits(mem_wb_ctrl_t)) reg_mem_wb_ctrl (
        .clk(clk), .reset(reset), .stall(1'b0), .flush(wb_jump_req), // 如果当前指令触发了异常，阻止前方的旧指令写入 WB
        .data_in(mem_wb_in.ctrl), .data_out(mem_wb_out.ctrl)
    );
    pipeline_reg #($bits(mem_wb_data_t)) reg_mem_wb_data (
        .clk(clk), .reset(reset), .stall(1'b0), .flush(1'b0), 
        .data_in(mem_wb_in.data), .data_out(mem_wb_out.data)
    );

    logic [63:0] difftest_mstatus, difftest_mip, difftest_mie;
    logic [63:0] difftest_mscratch, difftest_mcause, difftest_mtval;
    logic [63:0] difftest_mcycle, difftest_mhartid;
    logic [63:0] difftest_medeleg, difftest_mideleg;
    logic [63:0] difftest_stvec, difftest_sscratch, difftest_sepc, difftest_scause, difftest_stval;

    csr_regfile csr_unit (
        .clk(clk), .reset(reset),
        .ra(id_ex_out.data.csr_addr), .rd_val(csr_rdata),
        
        .we(mem_wb_out.ctrl.is_csr && mem_wb_out.ctrl.valid),
        .wa(mem_wb_out.data.csr_addr),
        .wd(mem_wb_out.data.csr_wdata),
        
        // 异常专用管脚
        .wb_is_mret (mem_wb_out.ctrl.is_mret && mem_wb_out.ctrl.valid),
        .wb_is_ecall(mem_wb_out.ctrl.is_ecall&& mem_wb_out.ctrl.valid),
        .wb_is_sret (mem_wb_out.ctrl.is_sret && mem_wb_out.ctrl.valid),
        .wb_pc(mem_wb_out.data.pc),
        .priv_mode(priv_mode),
        .trap_target(csr_trap_target),

        .csr_mstatus(difftest_mstatus), .csr_mtvec(difftest_mtvec), .csr_mip(difftest_mip), 
        .csr_mie(difftest_mie), .csr_mscratch(difftest_mscratch), .csr_mcause(difftest_mcause), 
        .csr_mtval(difftest_mtval), .csr_mepc(difftest_mepc), .csr_mcycle(difftest_mcycle), 
        .csr_mhartid(difftest_mhartid), .csr_satp(difftest_satp),
        .csr_medeleg(difftest_medeleg), .csr_mideleg(difftest_mideleg),
        .csr_stvec(difftest_stvec), .csr_sscratch(difftest_sscratch),
        .csr_sepc(difftest_sepc), .csr_scause(difftest_scause), .csr_stval(difftest_stval)
    );
    
`ifdef VERILATOR
    logic [63:0] cycle_cnt, instr_cnt;
    logic [63:0] total_br_cnt, mispredict_cnt;

    always_ff @(posedge clk) begin
        if (reset) begin 
            cycle_cnt <= 0;
            instr_cnt <= 0; 
            total_br_cnt <= 0;
            mispredict_cnt <= 0;
        end else begin 
            cycle_cnt <= cycle_cnt + 1;
            if (mem_wb_out.ctrl.valid) instr_cnt <= instr_cnt + 1; 
            
            // 2. 统计分支预测（在 EX 级流出时统计，避免 stall 导致重复计数）
            if (ex_valid) begin // ex_valid 在你的代码里已经定义过了 (id_ex_out.ctrl.valid && alu_ready)
                if (id_ex_out.ctrl.is_branch || id_ex_out.ctrl.is_jal || id_ex_out.ctrl.is_jalr) begin
                    total_br_cnt <= total_br_cnt + 1;
                    // 如果产生冲刷，说明预测失败了
                    if (ex_jump_flush) begin
                        mispredict_cnt <= mispredict_cnt + 1;
                    end
                end
            end
            
            // 3. 在程序结束（执行 TRAP 时）自动打印结果
            if (mem_wb_out.ctrl.valid && mem_wb_out.ctrl.is_trap) begin
                $display("\n====================================");
                $display("📈 Branch Prediction Performance");
                $display("====================================");
                $display("Total Branch/Jump Instrs : %0d", total_br_cnt);
                $display("Mispredicted Count       : %0d", mispredict_cnt);
                if (total_br_cnt > 0) begin
                    $display("Prediction Accuracy      : %.2f %%", 100 - (mispredict_cnt * 100.0 / total_br_cnt));
                end
                $display("====================================\n");
            end
        end
    end

    DifftestInstrCommit DifftestInstrCommit(
        .clock(clk), .coreid(difftest_mhartid[7:0]), .index(0), .valid(mem_wb_out.ctrl.valid), 
        .pc(mem_wb_out.data.pc), .instr(mem_wb_out.data.instr), 
        .skip((mem_wb_out.ctrl.mem_re | mem_wb_out.ctrl.mem_we) & (mem_wb_out.data.mem_addr[31] == 1'b0)), 
        .isRVC(0), .scFailed(0), .wen(mem_wb_out.ctrl.rf_we), .wdest({3'b0, mem_wb_out.data.rd}), .wdata(mem_wb_out.data.final_res)
    );

    DifftestArchIntRegState DifftestArchIntRegState (
        .clock(clk), .coreid(difftest_mhartid[7:0]),
        .gpr_0(gpr_state[0]),  .gpr_1(gpr_state[1]),  .gpr_2(gpr_state[2]),  .gpr_3(gpr_state[3]),
        .gpr_4(gpr_state[4]),  .gpr_5(gpr_state[5]),  .gpr_6(gpr_state[6]),  .gpr_7(gpr_state[7]),
        .gpr_8(gpr_state[8]),  .gpr_9(gpr_state[9]),  .gpr_10(gpr_state[10]), .gpr_11(gpr_state[11]),
        .gpr_12(gpr_state[12]), .gpr_13(gpr_state[13]), .gpr_14(gpr_state[14]), .gpr_15(gpr_state[15]),
        .gpr_16(gpr_state[16]), .gpr_17(gpr_state[17]), .gpr_18(gpr_state[18]), .gpr_19(gpr_state[19]),
        .gpr_20(gpr_state[20]), .gpr_21(gpr_state[21]), .gpr_22(gpr_state[22]), .gpr_23(gpr_state[23]),
        .gpr_24(gpr_state[24]), .gpr_25(gpr_state[25]), .gpr_26(gpr_state[26]), .gpr_27(gpr_state[27]),
        .gpr_28(gpr_state[28]), .gpr_29(gpr_state[29]), .gpr_30(gpr_state[30]), .gpr_31(gpr_state[31])
    );

    DifftestTrapEvent DifftestTrapEvent(
        .clock(clk), .coreid(difftest_mhartid[7:0]), .valid(mem_wb_out.ctrl.valid && mem_wb_out.ctrl.is_trap), 
        .code(gpr_state[10][2:0]), .pc(mem_wb_out.data.pc), .cycleCnt(cycle_cnt), .instrCnt(instr_cnt) 
    );

    DifftestCSRState DifftestCSRState(
        .clock(clk), .coreid(difftest_mhartid[7:0]), .priviledgeMode(priv_mode), 
        .mstatus(difftest_mstatus), .sstatus(difftest_mstatus & SSTATUS_MASK), 
        .mepc(difftest_mepc), .sepc(difftest_sepc),
        .mtval(difftest_mtval), .stval(difftest_stval), .mtvec(difftest_mtvec), .stvec(difftest_stvec), 
        .mcause(difftest_mcause), .scause(difftest_scause), .satp(difftest_satp),
        .mip(difftest_mip), .mie(difftest_mie), .mscratch(difftest_mscratch), 
        .sscratch(difftest_sscratch), .mideleg(difftest_mideleg), .medeleg(difftest_medeleg)
    );
`endif

endmodule
`endif