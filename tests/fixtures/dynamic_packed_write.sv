// SPDX-License-Identifier: Apache-2.0
// Reduced from the nested packed-array write pattern in CVA6 hpdcache.
module dynamic_packed_write (
    input logic clk, rst_n, enable,
    input logic row,
    input logic [1:0][2:0] word_index,
    input logic [63:0] data,
    output logic [1:0][7:0][63:0] buffer_q
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) buffer_q <= '0;
        else if (enable) buffer_q[row][word_index[row]] <= data;
    end
endmodule
