// Benchmark "c17" written by ABC on Sat May  2 15:31:10 2026

module c17 ( 
    G1gat, G2gat, G3gat, G6gat, G7gat,
    G22gat, G23gat  );
  input  G1gat, G2gat, G3gat, G6gat, G7gat;
  output G22gat, G23gat;
  wire new_new_n8, new_new_n9, new_new_n10, new_new_n11, new_new_n12,
    new_new_n13, new_new_n14, new_new_n15, new_new_n16, new_new_n18,
    new_new_n19;
  assign new_new_n8 = ~G2gat;
  assign new_new_n9 = ~G7gat;
  assign new_new_n10 = G3gat & G6gat;
  assign new_new_n11 = ~new_new_n10;
  assign new_new_n12 = G2gat & new_new_n11;
  assign new_new_n13 = ~new_new_n12;
  assign new_new_n14 = G1gat & G3gat;
  assign new_new_n15 = ~new_new_n14;
  assign new_new_n16 = new_new_n13 & new_new_n15;
  assign G22gat = ~new_new_n16;
  assign new_new_n18 = new_new_n8 & new_new_n9;
  assign new_new_n19 = ~new_new_n18;
  assign G23gat = new_new_n11 & new_new_n19;
endmodule


