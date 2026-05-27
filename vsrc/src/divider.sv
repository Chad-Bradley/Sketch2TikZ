`ifndef __DIVIDER_SV
`define __DIVIDER_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module divider import common::*; (
    input  logic        clk, reset,
    input  logic [63:0] a, b,
    input  alu_op_t     op,
    input  logic        is_word_op,
    input  logic        valid_in,
    output logic        ready_out,
    output logic[63:0] res
);
    typedef enum logic [2:0] { IDLE, PREP1, PREP2, CALC, DONE, FINISH } state_t;
    state_t state;

    logic [4:0]  count;
    logic [63:0] a_reg;       
    logic [63:0] q_reg;       
    logic [63:0] rem_reg;     
    logic [63:0] divisor_reg; 
    
    logic[67:0] b_3x_reg, b_5x_reg, b_7x_reg, b_9x_reg, b_11x_reg, b_13x_reg, b_15x_reg; 

    logic [63:0] abs_a_reg;        
    logic[63:0] abs_b_reg;        
    logic [63:0] op_a_reg;
    logic [63:0] res_reg;

    logic is_signed_div;
    logic res_sign_neg;
    logic rem_sign_neg;
    logic div_by_0_reg;
    logic ovf_reg;

    assign is_signed_div = (op == ALU_DIV || op == ALU_REM || op == ALU_DIVW || op == ALU_REMW);

    logic [63:0] op_a_comb, op_b_comb;
    logic [63:0] abs_a_comb, abs_b_comb;
    logic div_by_0_comb, ovf_comb;

    assign op_a_comb = is_word_op ? (is_signed_div ? {{32{a[31]}}, a[31:0]} : {32'b0, a[31:0]}) : a;
    assign op_b_comb = is_word_op ? (is_signed_div ? {{32{b[31]}}, b[31:0]} : {32'b0, b[31:0]}) : b;
    assign abs_a_comb = (is_signed_div && op_a_comb[63]) ? -op_a_comb : op_a_comb;
    assign abs_b_comb = (is_signed_div && op_b_comb[63]) ? -op_b_comb : op_b_comb;

    assign div_by_0_comb = (op_b_comb == '0);
    assign ovf_comb = (!is_word_op && is_signed_div && op_a_comb == 64'h80000000_00000000 && op_b_comb == 64'hFFFFFFFF_FFFFFFFF) ||
                      ( is_word_op && is_signed_div && op_a_comb == 64'hFFFFFFFF_80000000 && op_b_comb == 64'hFFFFFFFF_FFFFFFFF);

    // 计算前导零以跳过多余的迭代计算
    logic [4:0] skip_comb;
    always_comb begin
        skip_comb = 5'd0;
        for (int i = 63; i >= 0; i--) begin
            if (abs_a_reg[i]) begin
                skip_comb = 5'((63 - i) / 4);
                break;
            end
        end
    end

    // ==========================================
    // 旁路直通逻辑计算 
    // 仅使用比较器和加法器，避免深层组合逻辑
    // ==========================================
    logic[63:0] res_done_val, res_byp_val;
    logic[63:0] final_done, final_byp;
    logic [63:0] final_eq_byp, final_b1_byp;
    
    assign res_done_val = (op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) ? q_reg : rem_reg;
    assign res_byp_val  = (op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) ? 64'd0 : abs_a_reg;

    always_comb begin
        // 正常计算完成或 abs(a) < abs(b) 的旁路结果
        if ((op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) && res_sign_neg) begin
            final_done = -res_done_val;
            final_byp  = -res_byp_val;
        end else if ((op == ALU_REM || op == ALU_REMU || op == ALU_REMW || op == ALU_REMUW) && rem_sign_neg) begin
            final_done = -res_done_val;
            final_byp  = -res_byp_val;
        end else begin
            final_done = res_done_val;
            final_byp  = res_byp_val;
        end

        // 针对 abs(a) == abs(b) 的旁路结果 (商为1，余数为0)
        if (op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) begin
            final_eq_byp = res_sign_neg ? 64'hFFFFFFFF_FFFFFFFF : 64'd1;
        end else begin
            final_eq_byp = 64'd0; 
        end

        // 针对 abs(b) == 1 的旁路结果 (商为a，余数为0)
        if (op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) begin
            final_b1_byp = res_sign_neg ? -abs_a_reg : abs_a_reg;
        end else begin
            final_b1_byp = 64'd0;
        end
    end

    // ==========================================
    // 基数-16 计算树
    // ==========================================
    logic [68:0] pr; 
    logic [67:0] m [15:1];
    logic [68:0] sub[15:1];
    logic [63:0] nrem;
    logic [3:0]  nq;

    always_comb begin
        pr = {1'b0, rem_reg, a_reg[63:60]};
        
        m[1]  = {4'b0, divisor_reg};
        m[2]  = {3'b0, divisor_reg, 1'b0};
        m[3]  = b_3x_reg;
        m[4]  = {2'b0, divisor_reg, 2'b0};
        m[5]  = b_5x_reg;
        m[6]  = {b_3x_reg[66:0], 1'b0}; 
        m[7]  = b_7x_reg;
        m[8]  = {1'b0, divisor_reg, 3'b0};
        m[9]  = b_9x_reg;
        m[10] = {b_5x_reg[66:0], 1'b0};
        m[11] = b_11x_reg;
        m[12] = {b_3x_reg[65:0], 2'b00};
        m[13] = b_13x_reg;
        m[14] = {b_7x_reg[66:0], 1'b0};
        m[15] = b_15x_reg;

        for (int i = 1; i <= 15; i++) begin
            sub[i] = pr - {1'b0, m[i]};
        end
        
        if (!sub[15][68])      begin nq = 4'd15; nrem = sub[15][63:0]; end
        else if (!sub[14][68]) begin nq = 4'd14; nrem = sub[14][63:0]; end
        else if (!sub[13][68]) begin nq = 4'd13; nrem = sub[13][63:0]; end
        else if (!sub[12][68]) begin nq = 4'd12; nrem = sub[12][63:0]; end
        else if (!sub[11][68]) begin nq = 4'd11; nrem = sub[11][63:0]; end
        else if (!sub[10][68]) begin nq = 4'd10; nrem = sub[10][63:0]; end
        else if (!sub[9][68])  begin nq = 4'd9;  nrem = sub[9][63:0]; end
        else if (!sub[8][68])  begin nq = 4'd8;  nrem = sub[8][63:0]; end
        else if (!sub[7][68])  begin nq = 4'd7;  nrem = sub[7][63:0]; end
        else if (!sub[6][68])  begin nq = 4'd6;  nrem = sub[6][63:0]; end
        else if (!sub[5][68])  begin nq = 4'd5;  nrem = sub[5][63:0]; end
        else if (!sub[4][68])  begin nq = 4'd4;  nrem = sub[4][63:0]; end
        else if (!sub[3][68])  begin nq = 4'd3;  nrem = sub[3][63:0]; end
        else if (!sub[2][68])  begin nq = 4'd2;  nrem = sub[2][63:0]; end
        else if (!sub[1][68])  begin nq = 4'd1;  nrem = sub[1][63:0]; end
        else                   begin nq = 4'd0;  nrem = pr[63:0];      end
    end

    // ==========================================
    // 状态机
    // ==========================================
    always_ff @(posedge clk) begin
        if (reset) begin
            state        <= IDLE;
            count        <= 5'd0;
            a_reg        <= 64'd0;
            q_reg        <= 64'd0;
            rem_reg      <= 64'd0;
            divisor_reg  <= 64'd0;
            abs_a_reg    <= 64'd0;
            abs_b_reg    <= 64'd0;
            op_a_reg     <= 64'd0;
            res_reg      <= 64'd0;
            b_3x_reg     <= 68'd0; b_5x_reg  <= 68'd0; b_7x_reg  <= 68'd0;
            b_9x_reg     <= 68'd0; b_11x_reg <= 68'd0; b_13x_reg <= 68'd0; b_15x_reg <= 68'd0;
            res_sign_neg <= 1'b0; rem_sign_neg <= 1'b0;
            div_by_0_reg <= 1'b0; ovf_reg      <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    if (valid_in) begin
                        op_a_reg     <= op_a_comb;
                        abs_a_reg    <= abs_a_comb;
                        abs_b_reg    <= abs_b_comb;
                        div_by_0_reg <= div_by_0_comb;
                        ovf_reg      <= ovf_comb;
                        res_sign_neg <= is_signed_div && (op_a_comb[63] ^ op_b_comb[63]) && (op_b_comb != '0);
                        rem_sign_neg <= is_signed_div && op_a_comb[63];
                        state        <= PREP1;
                    end
                end

                PREP1: begin
                    if (div_by_0_reg) begin
                        logic [63:0] val0;
                        val0 = (op == ALU_DIV || op == ALU_DIVU || op == ALU_DIVW || op == ALU_DIVUW) ? 64'hFFFFFFFF_FFFFFFFF : op_a_reg;
                        res_reg <= is_word_op ? {{32{val0[31]}}, val0[31:0]} : val0;
                        state   <= FINISH;
                    end else if (ovf_reg) begin
                        logic[63:0] val_ovf;
                        val_ovf = (op == ALU_DIV) ? 64'h80000000_00000000 : ((op == ALU_DIVW) ? 64'hFFFFFFFF_80000000 : 64'b0);
                        res_reg <= is_word_op ? {{32{val_ovf[31]}}, val_ovf[31:0]} : val_ovf;
                        state   <= FINISH;
                    end else if (abs_a_reg < abs_b_reg) begin
                        res_reg <= is_word_op ? {{32{final_byp[31]}}, final_byp[31:0]} : final_byp;
                        state   <= FINISH;
                    // 新增时序安全的特判1：两数绝对值相等直接出结果
                    end else if (abs_a_reg == abs_b_reg) begin
                        res_reg <= is_word_op ? {{32{final_eq_byp[31]}}, final_eq_byp[31:0]} : final_eq_byp;
                        state   <= FINISH;
                    // 新增时序安全的特判2：除数为1直接出结果
                    end else if (abs_b_reg == 64'd1) begin
                        res_reg <= is_word_op ? {{32{final_b1_byp[31]}}, final_b1_byp[31:0]} : final_b1_byp;
                        state   <= FINISH;
                    end else begin
                        divisor_reg <= abs_b_reg;
                        // 利用 skip_comb 跳过 a_reg 的前导零，动态减少 CALC 阶段迭代次数
                        a_reg       <= abs_a_reg << {skip_comb, 2'b00}; 
                        count       <= skip_comb;
                        rem_reg     <= 64'd0;
                        q_reg       <= 64'd0;

                        b_3x_reg <= ({4'b0, abs_b_reg} << 1) + {4'b0, abs_b_reg};
                        b_5x_reg <= ({4'b0, abs_b_reg} << 2) + {4'b0, abs_b_reg};
                        b_7x_reg <= ({4'b0, abs_b_reg} << 3) - {4'b0, abs_b_reg};
                        b_9x_reg <= ({4'b0, abs_b_reg} << 3) + {4'b0, abs_b_reg};

                        state <= PREP2;
                    end
                end

                PREP2: begin
                    b_11x_reg <= ({4'b0, divisor_reg} << 3) + b_3x_reg;
                    b_13x_reg <= ({4'b0, divisor_reg} << 4) - b_3x_reg;
                    b_15x_reg <= ({4'b0, divisor_reg} << 4) - {4'b0, divisor_reg};
                    
                    state <= CALC;
                end

                CALC: begin
                    rem_reg <= nrem;
                    a_reg   <= a_reg << 4;
                    q_reg   <= {q_reg[59:0], nq};
                    count   <= count + 5'd1;
                    
                    if (count == 5'd15) begin
                        state <= DONE;
                    end
                end

                DONE: begin
                    res_reg <= is_word_op ? {{32{final_done[31]}}, final_done[31:0]} : final_done;
                    state   <= FINISH;
                end

                FINISH: state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end

    assign res = res_reg;
    assign ready_out = (state == FINISH);

endmodule
`endif