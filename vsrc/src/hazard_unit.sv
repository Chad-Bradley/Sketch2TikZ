`ifndef __HAZARD_UNIT_SV
`define __HAZARD_UNIT_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module hazard_unit import common::*; (
    input  logic         if_not_ready,  
    input  logic         ex_not_ready,  
    input  logic         lsu_not_ready, 
    
    input  logic [4:0]   id_ex_rd,      
    input  logic         id_ex_mem_re,  
    input  logic [4:0]   dec_rs1,       
    input  logic [4:0]   dec_rs2,       
    
    output logic         pc_stall,
    output logic         if_id_stall,
    output logic         id_ex_stall,
    output logic         ex_mem_stall,
    
    output logic         if_id_flush,
    output logic         id_ex_flush,
    
    input  logic         jump_flush,   
    input  logic         id_jump_req,
    input  logic         wb_jump_req     // 新增：WB 冲刷
);
    logic load_use_hazard;
    assign load_use_hazard = id_ex_mem_re && (id_ex_rd != 5'b0) && 
                             ((id_ex_rd == dec_rs1) || (id_ex_rd == dec_rs2));

    logic real_load_use;
    assign real_load_use = load_use_hazard;

    logic real_if_not_ready;
    assign real_if_not_ready = if_not_ready;

    always_comb begin
        pc_stall     = lsu_not_ready || ex_not_ready || real_load_use || real_if_not_ready;
        if_id_stall  = lsu_not_ready || ex_not_ready || real_load_use || real_if_not_ready;
        id_ex_stall  = lsu_not_ready || ex_not_ready;
        ex_mem_stall = lsu_not_ready;

        // wb_jump_req 拥有全流水线穿透力，不管 stalls 状态如何都会清洗掉上游管线
        id_ex_flush  = wb_jump_req || ( !(lsu_not_ready || ex_not_ready) && 
                       (jump_flush || real_load_use || (real_if_not_ready && !id_jump_req)) );

        if_id_flush  = wb_jump_req || ( !(lsu_not_ready || ex_not_ready) && 
                       (jump_flush || (id_jump_req && !id_ex_stall)) );
    end
endmodule
`endif