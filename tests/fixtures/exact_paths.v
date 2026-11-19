module leaf(input A, output Y);
  assign Y = A;
endmodule
module branch(input A, output Y);
  leaf b (.A(A), .Y(Y));
endmodule
module exact_paths(input \d_in[0] , input [3:0] d_in, output [3:0] y);
  leaf \a.b  (.A(\d_in[0] ), .Y(y[0]));
  branch a (.A(d_in[0]), .Y(y[1]));
  leaf \$yosys$name  (.A(d_in[1]), .Y(y[2]));
  leaf \a/b[]$  (.A(d_in[2]), .Y(y[3]));
endmodule
