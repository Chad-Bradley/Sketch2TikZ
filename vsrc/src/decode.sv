`ifndef __DECODE_SV
`define __DECODE_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module decode import common::*; (
    input  logic [31:0] instr,
    output logic [4:0]  rs1, rs2, rd,
    output logic        rf_we,
    output logic [63:0] imm,
    output alu_op_t     alu_op,
    output logic        alu_src_sel,
    output logic        is_word_op,
    output logic        is_m_op,
    output logic        is_trap,
    // 内存控制信号
    output logic        mem_we,
    output logic        mem_re,
    output msize_t      mem_size,
    output logic        mem_unsigned,
    
    // 控制流信号
    output logic        is_branch,
    output logic        is_jal,
    output logic        is_jalr,
    output logic        is_auipc,
    output br_type_t    br_type,
    
    // CSR & 异常控制信号
    output logic        is_csr,
    output csr_op_t     csr_op,
    output logic        csr_use_imm,
    output logic        is_mret,
    output logic        is_ecall,
    output logic        is_sret
);
    logic [6:0]  opcode ;
    logic [2:0]  funct3 ;
    logic [6:0]  funct7 ;

    assign opcode = instr[6:0];
    assign funct3 = instr[14:12];
    assign funct7 = instr[31:25];

    assign rs1 = (opcode == 7'b0110111 || opcode == 7'b0010111 || opcode == 7'b1101111) ? 5'b0 : instr[19:15]; 
    assign rs2 = instr[24:20];
    assign rd  = instr[11:7];

    always_comb begin
        rf_we        = 0;
        alu_op       = ALU_ADD;
        imm          = '0;
        alu_src_sel  = 0;
        is_word_op   = 0;
        is_m_op      = (funct7 == 7'b0000001) && (opcode == 7'b0110011 || opcode == 7'b0111011);
        is_trap      = 0;
        mem_we       = 0;
        mem_re       = 0;
        mem_size     = MSIZE1;
        mem_unsigned = 0;
        is_branch    = 0;
        is_jal       = 0;
        is_jalr      = 0;
        is_auipc     = 0;
        br_type      = BR_NONE;
        is_csr       = 0;
        csr_op       = CSR_NONE;
        csr_use_imm  = 0;
        is_mret      = 0;
        is_ecall     = 0;
        is_sret      = 0;

        case (opcode)
            7'b1101011: begin // TRAP (NEMU/Spike)
                if (instr == 32'h0005006b) is_trap = 1'b1;
            end
            
            7'b1110011: begin // SYSTEM (CSR & EBREAK/ECALL/MRET)
                if (funct3 != 3'b000) begin 
                    rf_we       = 1;
                    is_csr      = 1;
                    imm         = {{52{1'b0}}, instr[31:20]}; 
                    csr_use_imm = funct3[2];                  
                    case (funct3[1:0])
                        2'b01: csr_op = CSR_RW;
                        2'b10: csr_op = CSR_RS;
                        2'b11: csr_op = CSR_RC;
                        default: csr_op = CSR_NONE;
                    endcase
                end else begin 
                    // 特权指令判定
                    if (instr[31:20] == 12'h302) begin
                        is_mret = 1'b1;
                    end else if (instr[31:20] == 12'h102) begin
                        is_sret = 1'b1;
                    end else if (instr[31:20] == 12'h000) begin
                        is_ecall = 1'b1;
                    end else if (instr == 32'h00100073) begin
                        is_trap = 1'b1;
                    end
                end
            end

            7'b0110111: begin // LUI
                rf_we = 1;
                alu_src_sel = 1;
                alu_op = ALU_ADD;
                imm = {{32{instr[31]}}, instr[31:12], 12'b0};
            end
            
            7'b0010111: begin // AUIPC
                rf_we = 1;
                alu_src_sel = 1;
                alu_op = ALU_ADD;
                imm = {{32{instr[31]}}, instr[31:12], 12'b0};
                is_auipc = 1;
            end

            7'b1101111: begin // JAL
                rf_we = 1;
                is_jal = 1;
                imm = {{44{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0};
            end

            7'b1100111: begin // JALR
                rf_we = 1;
                is_jalr = 1;
                imm = {{52{instr[31]}}, instr[31:20]};
            end

            7'b1100011: begin // BRANCH
                rf_we = 0;
                is_branch = 1;
                imm = {{52{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0};
                case (funct3)
                    3'b000: br_type = BR_BEQ;
                    3'b001: br_type = BR_BNE;
                    3'b100: br_type = BR_BLT;
                    3'b101: br_type = BR_BGE;
                    3'b110: br_type = BR_BLTU;
                    3'b111: br_type = BR_BGEU;
                    default: br_type = BR_NONE;
                endcase
            end

            7'b0000011: begin // LOAD
                rf_we = 1;
                alu_src_sel = 1;
                alu_op = ALU_ADD;
                mem_re = 1;
                imm = {{52{instr[31]}}, instr[31:20]};
                mem_unsigned = funct3[2];
                case (funct3[1:0])
                    2'b00: mem_size = MSIZE1;
                    2'b01: mem_size = MSIZE2;
                    2'b10: mem_size = MSIZE4;
                    2'b11: mem_size = MSIZE8;
                endcase
            end

            7'b0100011: begin // STORE
                rf_we = 0;
                alu_src_sel = 1;
                alu_op = ALU_ADD;
                mem_we = 1;
                imm = {{52{instr[31]}}, instr[31:25], instr[11:7]};
                case (funct3[1:0])
                    2'b00: mem_size = MSIZE1;
                    2'b01: mem_size = MSIZE2;
                    2'b10: mem_size = MSIZE4;
                    2'b11: mem_size = MSIZE8;
                endcase
            end

            7'b0010011: begin // OP-IMM
                rf_we = 1;
                alu_src_sel = 1;
                imm = {{52{instr[31]}}, instr[31:20]};
                case (funct3)
                    3'b000: alu_op = ALU_ADD;
                    3'b010: alu_op = ALU_SLT; 
                    3'b011: alu_op = ALU_SLTU;
                    3'b100: alu_op = ALU_XOR;
                    3'b110: alu_op = ALU_OR;
                    3'b111: alu_op = ALU_AND;
                    3'b001: alu_op = ALU_SLL;
                    3'b101: alu_op = (funct7[5]) ? ALU_SRA : ALU_SRL;
                    default: alu_op = ALU_ADD;
                endcase
            end

            7'b0011011: begin // OP-IMM-32
                rf_we = 1;
                alu_src_sel = 1;
                is_word_op = 1;
                imm = {{52{instr[31]}}, instr[31:20]};
                case (funct3)
                    3'b000: alu_op = ALU_ADD;
                    3'b001: alu_op = ALU_SLL;
                    3'b101: alu_op = (funct7[5]) ? ALU_SRA : ALU_SRL;
                    default: alu_op = ALU_ADD;
                endcase
            end

            7'b0110011: begin // OP & M-Extension
                rf_we = 1;
                alu_src_sel = 0;
                if (is_m_op) begin
                    case (funct3)
                        3'b000: alu_op = ALU_MUL;
                        3'b100: alu_op = ALU_DIV;
                        3'b101: alu_op = ALU_DIVU;
                        3'b110: alu_op = ALU_REM;
                        3'b111: alu_op = ALU_REMU;
                        default: alu_op = ALU_MUL;
                    endcase
                end else begin
                    case (funct3)
                        3'b000: alu_op = (funct7[5]) ? ALU_SUB : ALU_ADD;
                        3'b001: alu_op = ALU_SLL;
                        3'b010: alu_op = ALU_SLT; 
                        3'b011: alu_op = ALU_SLTU;
                        3'b100: alu_op = ALU_XOR;
                        3'b101: alu_op = (funct7[5]) ? ALU_SRA : ALU_SRL;
                        3'b110: alu_op = ALU_OR;
                        3'b111: alu_op = ALU_AND;
                        default: alu_op = ALU_ADD;
                    endcase
                end
            end

            7'b0111011: begin // OP-32 & M-Extension
                rf_we = 1;
                alu_src_sel = 0;
                is_word_op = 1;
                if (is_m_op) begin
                    case (funct3)
                        3'b000: alu_op = ALU_MULW;
                        3'b100: alu_op = ALU_DIVW;
                        3'b101: alu_op = ALU_DIVUW;
                        3'b110: alu_op = ALU_REMW;
                        3'b111: alu_op = ALU_REMUW;
                        default: alu_op = ALU_MULW;
                    endcase
                end else begin
                    case (funct3)
                        3'b000: alu_op = (funct7[5]) ? ALU_SUB : ALU_ADD;
                        3'b001: alu_op = ALU_SLL;
                        3'b101: alu_op = (funct7[5]) ? ALU_SRA : ALU_SRL;
                        default: alu_op = ALU_ADD;
                    endcase
                end
            end

            default: ;
        endcase
    end
endmodule
`endif