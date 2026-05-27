`ifndef __MEMORY_SV
`define __MEMORY_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module memory import common::*;(
    input  logic       clk, rst,
    input  logic       execute_ok,
    input  word_t      ex_data,
    input  logic       mem_read,
    input  logic       mem_write,
    input  u3          funct3,
    input  word_t      store_data,
    output dbus_req_t  dreq,
    input  dbus_resp_t dresp,
    output logic       mem_ok,
    output word_t      mem_data,
    output logic       mem_is_mem
);
    logic  mem_valid;
    word_t data_reg;
    logic  mem_resp_ok;
    assign mem_resp_ok = mem_valid && dresp.data_ok && dresp.addr_ok;

    always_ff @(posedge clk) begin
        if (rst) begin
            mem_valid <= 1'b0;
            data_reg  <= 64'h0;
        end else begin
            // 收到 dresp 响应
            if (mem_resp_ok) begin
                mem_valid <= 1'b0;
                data_reg  <= dresp.data;
            end

            // 发起 dreq 请求
            if (execute_ok && !mem_valid && (mem_read || mem_write)) begin
                mem_valid <= 1'b1;
            end
        end
    end

    assign dreq.valid = mem_valid;
    assign dreq.addr  = ex_data;

    logic [7:0] byte_mask;
    assign byte_mask = (8'b1 << (1 << funct3[1:0])) - 8'b1;
    
    always_comb begin
        dreq.size   = MSIZE8;
        dreq.strobe = 8'b0;
        dreq.data   = store_data;

        if (mem_read) begin
            dreq.size = msize_t'({1'b0, funct3[1:0]});
        end else if (mem_write) begin
            dreq.size   = msize_t'({1'b0, funct3[1:0]});
            dreq.strobe = byte_mask << ex_data[2:0];
            dreq.data   = store_data << {ex_data[2:0], 3'b0};
        end
    end

    // 寄存器中有有效数据时使用，否则使用实时值
    word_t raw_data;
    assign raw_data = mem_resp_ok ? dresp.data : data_reg;
    
    // 提取从内存中读取的数据并扩展
    word_t shifted_data;
    assign shifted_data = raw_data >> {ex_data[2:0], 3'b0};

    word_t mem_read_data;
    always_comb begin
        case (funct3)
            3'b011:  mem_read_data = shifted_data;                                  // ld
            3'b010:  mem_read_data = {{32{shifted_data[31]}}, shifted_data[31:0]};  // lw
            3'b110:  mem_read_data = {32'b0, shifted_data[31:0]};                   // lwu
            3'b001:  mem_read_data = {{48{shifted_data[15]}}, shifted_data[15:0]};  // lh
            3'b101:  mem_read_data = {48'b0, shifted_data[15:0]};                   // lhu
            3'b000:  mem_read_data = {{56{shifted_data[7]}}, shifted_data[7:0]};    // lb
            3'b100:  mem_read_data = {56'b0, shifted_data[7:0]};                    // lbu
            default: mem_read_data = shifted_data;
        endcase
    end

    assign mem_data      = mem_read ? mem_read_data : ex_data;
    assign mem_ok        = execute_ok && !mem_read && !mem_write  // 非访存立即完成
                        || mem_resp_ok;                           // 访存收到 dresp 响应后完成
    assign mem_is_mem    = mem_read || mem_write;
    
endmodule
`endif
