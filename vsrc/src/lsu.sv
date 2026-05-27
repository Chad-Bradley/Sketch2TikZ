`ifndef __LSU_SV
`define __LSU_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module lsu import common::*; (
    input  logic         clk, reset,
    
    // 来自执行阶段的请求信号
    input  logic         valid_in,     // 当前指令是否有效
    input  logic         mem_re,       // 读使能
    input  logic         mem_we,       // 写使能
    input  msize_t       mem_size,     // 访存大小 (1, 2, 4, 8 字节)
    input  logic         mem_unsigned, // 是否为无符号加载
    
    input  logic [63:0]  addr,         // 访存地址 (来自 ALU 结果)
    input  logic [63:0]  wdata_src,    // 待写入数据 (来自寄存器 rs2)
    
    output logic [63:0]  rdata_out,    // 处理后的读出数据
    output logic         lsu_ready,    // 访存是否完成
    
    // 物理总线接口
    output dbus_req_t    dreq,
    input  dbus_resp_t   dresp
);
    // 地址低3位偏移
    logic [2:0] offset;
    assign offset = addr[2:0];

    // --- 请求部分 ---
    assign dreq.valid = valid_in && (mem_re || mem_we);
    assign dreq.addr  = addr;
    assign dreq.size  = mem_size;
    assign dreq.data  = wdata_src << (8 * offset);

    always_comb begin
        if (mem_we && valid_in) begin
            case (mem_size)
                MSIZE1: dreq.strobe = 8'b0000_0001 << offset;
                MSIZE2: dreq.strobe = 8'b0000_0011 << offset;
                MSIZE4: dreq.strobe = 8'b0000_1111 << offset;
                MSIZE8: dreq.strobe = 8'b1111_1111;
                default: dreq.strobe = 8'b0;
            endcase
        end else begin
            dreq.strobe = 8'b0;
        end
    end

    // --- 响应处理部分 ---
    logic [63:0] shifted_data;
    assign shifted_data = dresp.data >> (8 * offset);

    always_comb begin
        case (mem_size)
            MSIZE1: rdata_out = mem_unsigned ? {56'b0, shifted_data[7:0]}  : {{56{shifted_data[7]}},  shifted_data[7:0]};
            MSIZE2: rdata_out = mem_unsigned ? {48'b0, shifted_data[15:0]} : {{48{shifted_data[15]}}, shifted_data[15:0]};
            MSIZE4: rdata_out = mem_unsigned ? {32'b0, shifted_data[31:0]} : {{32{shifted_data[31]}}, shifted_data[31:0]};
            default: rdata_out = shifted_data; // MSIZE8
        endcase
    end

    // 如果没有访存请求，直接 ready；如果有，等待总线 data_ok
    assign lsu_ready = (!dreq.valid) || dresp.data_ok;

endmodule
`endif