`ifndef __MULTIPLIER_SV
`define __MULTIPLIER_SV

`ifdef VERILATOR
`include "include/common.sv"
`endif

module multiplier import common::*; (
    input  logic        clk, reset,
    input  logic [63:0] a, b,
    input  alu_op_t     op,
    input  logic        is_word_op,
    input  logic        valid_in,
    output logic        ready_out,
    output logic[63:0] res
);

    typedef enum logic[1:0] { IDLE, CALC, MERGE, DONE } state_t;
    state_t state;

    logic [63:0] a_reg;
    logic [63:0] b_reg;
    logic[63:0] sum_reg;
    logic [63:0] carry_reg;
    logic[63:0] res_reg;
    logic        booth_prev;
    logic        iters;

    assign ready_out = (state == DONE);

    logic [63:0] op_a, op_b;
    always_comb begin
        op_a = is_word_op ? {{32{a[31]}}, a[31:0]} : a;
        op_b = is_word_op ? {{32{b[31]}}, b[31:0]} : b;
    end

    // ==========================================
    // 平均情况优化 (Fast Path / Average Case) 探测逻辑
    // 100MHz (10ns) 周期极长，加这些简单的比较器对时序毫无压力
    // ==========================================
    logic a_is_zero, b_is_zero;
    logic a_is_one,  b_is_one;
    logic op_a_ext,  op_b_ext;

    always_comb begin
        a_is_zero = (op_a == 64'b0);
        b_is_zero = (op_b == 64'b0);
        a_is_one  = (op_a == 64'd1);
        b_is_one  = (op_b == 64'd1);
        
        // 探测高32位是否全是符号位延伸 (即不需要进入第二个 CALC 周期)
        op_a_ext  = (op_a[63:31] == 33'b0) || (op_a[63:31] == 33'h1_FFFF_FFFF);
        op_b_ext  = (op_b[63:31] == 33'b0) || (op_b[63:31] == 33'h1_FFFF_FFFF);
    end

    // ==========================================
    // 十六路 Booth-4 编码器
    // ==========================================
    logic [2:0]  booth_sel[15:0];
    logic [63:0] b_shifted [15:0];
    logic[63:0] pp_base   [15:0];
    logic [15:0] pp_add;

    always_comb begin
        booth_sel[0] = {a_reg[1], a_reg[0], booth_prev};
        for (int i = 1; i < 16; i++) begin
            booth_sel[i] = {a_reg[2*i+1], a_reg[2*i], a_reg[2*i-1]};
        end

        for (int i = 0; i < 16; i++) begin
            b_shifted[i] = b_reg << (2 * i);
        end
    end

    always_comb begin
        for (int i = 0; i < 16; i++) begin
            case (booth_sel[i])
                3'b000, 3'b111: begin pp_base[i] = 64'b0;                           pp_add[i] = 1'b0; end 
                3'b001, 3'b010: begin pp_base[i] = b_shifted[i];                    pp_add[i] = 1'b0; end 
                3'b011:         begin pp_base[i] = {b_shifted[i][62:0], 1'b0};      pp_add[i] = 1'b0; end 
                3'b100:         begin pp_base[i] = ~{b_shifted[i][62:0], 1'b0};     pp_add[i] = 1'b1; end 
                3'b101, 3'b110: begin pp_base[i] = ~b_shifted[i];                   pp_add[i] = 1'b1; end 
                default:        begin pp_base[i] = 64'b0;                           pp_add[i] = 1'b0; end
            endcase
        end
    end

    // ==========================================
    // 进位补偿压缩
    // ==========================================
    logic [4:0] pp_add_sum;
    logic [2:0] pp_add_lvl1 [7:0];
    logic [3:0] pp_add_lvl2 [3:0];
    logic [4:0] pp_add_lvl3 [1:0];

    always_comb begin
        for (int i = 0; i < 8; i++) pp_add_lvl1[i] = {2'b0, pp_add[2*i]} + {2'b0, pp_add[2*i+1]};
        for (int i = 0; i < 4; i++) pp_add_lvl2[i] = {1'b0, pp_add_lvl1[2*i]} + {1'b0, pp_add_lvl1[2*i+1]};
        for (int i = 0; i < 2; i++) pp_add_lvl3[i] = {1'b0, pp_add_lvl2[2*i]} + {1'b0, pp_add_lvl2[2*i+1]};
        pp_add_sum = pp_add_lvl3[0] + pp_add_lvl3[1];
    end

    // ==========================================
    // 6层 展平 CSA 压缩树 
    // ==========================================
    logic [63:0] csa_l0 [18:0];
    
    // 显式声明各层的中间进位变量，解决 Verilator 切片报错
    logic[63:0] csa_l1 [12:0]; 
    logic[63:0] cout1  [5:0];
    
    logic [63:0] csa_l2 [8:0];  
    logic [63:0] cout2  [3:0];
    
    logic [63:0] csa_l3 [5:0];  
    logic [63:0] cout3  [2:0];
    
    logic[63:0] csa_l4 [3:0];  
    logic [63:0] cout4  [1:0];
    
    logic [63:0] csa_l5[2:0];  
    logic [63:0] cout5;
    
    logic[63:0] csa_l6 [1:0];  
    logic [63:0] cout6;

    always_comb begin
        for(int i=0; i<16; i++) csa_l0[i] = pp_base[i];
        csa_l0[16] = sum_reg;        
        csa_l0[17] = carry_reg;      
        csa_l0[18] = {59'b0, pp_add_sum};

        // L1: 19 -> 13
        for(int i=0; i<6; i++) begin
            cout1[i] = (csa_l0[3*i] & csa_l0[3*i+1]) | (csa_l0[3*i+1] & csa_l0[3*i+2]) | (csa_l0[3*i] & csa_l0[3*i+2]);
            csa_l1[2*i]   = csa_l0[3*i] ^ csa_l0[3*i+1] ^ csa_l0[3*i+2];
            csa_l1[2*i+1] = {cout1[i][62:0], 1'b0}; // 赋予变量后再执行切片，100% 合法
        end
        csa_l1[12] = csa_l0[18];

        // L2: 13 -> 9
        for(int i=0; i<4; i++) begin
            cout2[i] = (csa_l1[3*i] & csa_l1[3*i+1]) | (csa_l1[3*i+1] & csa_l1[3*i+2]) | (csa_l1[3*i] & csa_l1[3*i+2]);
            csa_l2[2*i]   = csa_l1[3*i] ^ csa_l1[3*i+1] ^ csa_l1[3*i+2];
            csa_l2[2*i+1] = {cout2[i][62:0], 1'b0};
        end
        csa_l2[8] = csa_l1[12];

        // L3: 9 -> 6
        for(int i=0; i<3; i++) begin
            cout3[i] = (csa_l2[3*i] & csa_l2[3*i+1]) | (csa_l2[3*i+1] & csa_l2[3*i+2]) | (csa_l2[3*i] & csa_l2[3*i+2]);
            csa_l3[2*i]   = csa_l2[3*i] ^ csa_l2[3*i+1] ^ csa_l2[3*i+2];
            csa_l3[2*i+1] = {cout3[i][62:0], 1'b0};
        end

        // L4: 6 -> 4
        for(int i=0; i<2; i++) begin
            cout4[i] = (csa_l3[3*i] & csa_l3[3*i+1]) | (csa_l3[3*i+1] & csa_l3[3*i+2]) | (csa_l3[3*i] & csa_l3[3*i+2]);
            csa_l4[2*i]   = csa_l3[3*i] ^ csa_l3[3*i+1] ^ csa_l3[3*i+2];
            csa_l4[2*i+1] = {cout4[i][62:0], 1'b0};
        end

        // L5: 4 -> 3
        cout5 = (csa_l4[0] & csa_l4[1]) | (csa_l4[1] & csa_l4[2]) | (csa_l4[0] & csa_l4[2]);
        csa_l5[0] = csa_l4[0] ^ csa_l4[1] ^ csa_l4[2];
        csa_l5[1] = {cout5[62:0], 1'b0};
        csa_l5[2] = csa_l4[3];

        // L6: 3 -> 2
        cout6 = (csa_l5[0] & csa_l5[1]) | (csa_l5[1] & csa_l5[2]) | (csa_l5[0] & csa_l5[2]);
        csa_l6[0] = csa_l5[0] ^ csa_l5[1] ^ csa_l5[2];
        csa_l6[1] = {cout6[62:0], 1'b0};
    end

    logic early_exit;
    // 预判：剩余高位均为符号位，计算提前结束
    assign early_exit = (a_reg[63:31] == 33'b0) || (a_reg[63:31] == 33'h1_FFFF_FFFF);

    // ==========================================
    // 状态机
    // ==========================================
    always_ff @(posedge clk) begin
        if (reset) begin
            state      <= IDLE;
            a_reg      <= 64'b0;
            b_reg      <= 64'b0;
            sum_reg    <= 64'b0;
            carry_reg  <= 64'b0;
            res_reg    <= 64'b0;
            booth_prev <= 1'b0;
            iters      <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    if (valid_in) begin
                        // 优化1：0 和 1 的特判，直接跳到 DONE 状态旁路掉一切计算
                        if (a_is_zero || b_is_zero) begin
                            res_reg <= 64'b0;
                            state   <= DONE;
                        end else if (a_is_one) begin
                            res_reg <= op_b;
                            state   <= DONE;
                        end else if (b_is_one) begin
                            res_reg <= op_a;
                            state   <= DONE;
                        end else begin
                            // 优化2：操作数交换。
                            // 若 b 是短位数 (高位全零或全一)，而 a 不是，互换身份。
                            // 将使 a_reg_next 符合 early_exit，从而在第一拍直接跳出循环！
                            if (!op_a_ext && op_b_ext) begin
                                a_reg <= op_b;
                                b_reg <= op_a;
                            end else begin
                                a_reg <= op_a;
                                b_reg <= op_b;
                            end
                            
                            sum_reg    <= 64'b0; 
                            carry_reg  <= 64'b0;
                            booth_prev <= 1'b0;
                            iters      <= 1'b0;
                            state      <= CALC;
                        end
                    end
                end
                
                CALC: begin
                    sum_reg    <= csa_l6[0];
                    carry_reg  <= csa_l6[1];
                    
                    a_reg      <= { {32{a_reg[63]}}, a_reg[63:32] };
                    b_reg      <= b_reg << 32;
                    booth_prev <= a_reg[31];
                    iters      <= 1'b1;
                    
                    if (early_exit || iters == 1'b1) begin
                        state <= MERGE;
                    end
                end

                MERGE: begin
                    res_reg <= sum_reg + carry_reg;
                    state   <= DONE;
                end
                
                DONE: begin
                    state <= IDLE;
                end
                
                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

    // Word Op 依然走统一出口做符号扩展，与快速旁路相容
    assign res = is_word_op ? {{32{res_reg[31]}}, res_reg[31:0]} : res_reg;

endmodule
`endif