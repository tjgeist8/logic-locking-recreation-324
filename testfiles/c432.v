// Benchmark "c432" written by ABC on Fri May  1 10:29:44 2026

module c432 ( 
    G1GAT, G4GAT, G8GAT, G11GAT, G14GAT, G17GAT, G21GAT, G24GAT, G27GAT,
    G30GAT, G34GAT, G37GAT, G40GAT, G43GAT, G47GAT, G50GAT, G53GAT, G56GAT,
    G60GAT, G63GAT, G66GAT, G69GAT, G73GAT, G76GAT, G79GAT, G82GAT, G86GAT,
    G89GAT, G92GAT, G95GAT, G99GAT, G102GAT, G105GAT, G108GAT, G112GAT,
    G115GAT, enc_in_0, enc_in_1,
    G223GAT, G329GAT, G370GAT, G421GAT, G430GAT, G431GAT, G432GAT  );
  input  G1GAT, G4GAT, G8GAT, G11GAT, G14GAT, G17GAT, G21GAT, G24GAT,
    G27GAT, G30GAT, G34GAT, G37GAT, G40GAT, G43GAT, G47GAT, G50GAT, G53GAT,
    G56GAT, G60GAT, G63GAT, G66GAT, G69GAT, G73GAT, G76GAT, G79GAT, G82GAT,
    G86GAT, G89GAT, G92GAT, G95GAT, G99GAT, G102GAT, G105GAT, G108GAT,
    G112GAT, G115GAT, enc_in_0, enc_in_1;
  output G223GAT, G329GAT, G370GAT, G421GAT, G430GAT, G431GAT, G432GAT;
  wire new_n44, new_n45, new_n46, new_n47, new_n48, new_n49, new_n50,
    new_n51, new_n52, new_n53, new_n54, new_n55, new_n56, new_n57, new_n58,
    new_n59, new_n60, new_n61, new_n62, new_n63, new_n64, new_n65, new_n66,
    new_n67, new_n68, new_n69, new_n70, new_n71, new_n72, new_n73, new_n74,
    new_n75, new_n76, new_n77, new_n78, new_n79, new_n80, new_n81, new_n82,
    new_n83, new_n84, new_n85, new_n86, new_n87, new_n88, new_n89, new_n90,
    new_n91, new_n92, new_n93, new_n94, new_n95, new_n96, new_n98, new_n99,
    new_n100, new_n101, new_n102, new_n103, new_n104, new_n105, new_n106,
    new_n107, new_n108, new_n109, new_n110, new_n111, new_n112, new_n113,
    new_n114, new_n115, new_n116, new_n117, new_n118, new_n119, new_n120,
    new_n121, new_n122, new_n123, new_n124, new_n125, new_n126, new_n127,
    new_n128, new_n129, new_n130, new_n131, new_n132, new_n133, new_n134,
    new_n135, new_n136, new_n137, new_n138, new_n139, new_n140, new_n141,
    new_n142, new_n143, new_n144, new_n145, new_n146, new_n147, new_n148,
    new_n149, new_n150, new_n151, new_n153, new_n154, new_n155, new_n156,
    new_n157, new_n158, new_n159, new_n160, new_n161, new_n162, new_n163,
    new_n164, new_n165, new_n166, new_n167, new_n168, new_n169, new_n170,
    new_n171, new_n172, new_n173, new_n174, new_n175, new_n176, new_n177,
    new_n178, new_n179, new_n180, new_n181, new_n182, new_n183, new_n184,
    new_n185, new_n186, new_n187, new_n188, new_n189, new_n190, new_n191,
    new_n192, new_n193, new_n194, new_n195, new_n196, new_n197, new_n198,
    new_n199, new_n200, new_n201, new_n202, new_n203, new_n204, new_n205,
    new_n206, new_n207, new_n208, new_n209, new_n210, new_n212, new_n213,
    new_n214, new_n215, new_n216, new_n217, new_n218, new_n219, new_n220,
    new_n221, new_n222, new_n223, new_n224, new_n225, new_n226, new_n227,
    new_n228, new_n229, new_n230, new_n231, new_n232, new_n233, new_n234,
    new_n235, new_n236, new_n237, new_n238, new_n239, new_n240, new_n241,
    new_n242, new_n243, new_n244, new_n245, new_n246, new_n247, new_n248,
    new_n249, new_n250, new_n252, new_n253, new_n254, new_n255, new_n256,
    new_n257, new_n258, new_n259, new_n260, new_n262, new_n263, new_n264,
    new_n265, new_n266, new_n267, new_n268, new_n269, new_n270, new_n272,
    new_n273, new_n274, new_n275, new_n276, new_n277, new_n278, new_n279,
    new_n280, new_n281, new_n282, new_n283, new_n284;
  assign new_n44 = ~G1GAT;
  assign new_n45 = ~G8GAT;
  assign new_n46 = ~G11GAT;
  assign new_n47 = ~G14GAT;
  assign new_n48 = ~G21GAT;
  assign new_n49 = ~G24GAT;
  assign new_n50 = ~G27GAT;
  assign new_n51 = ~G34GAT;
  assign new_n52 = ~G37GAT;
  assign new_n53 = ~G40GAT;
  assign new_n54 = ~G47GAT;
  assign new_n55 = ~G50GAT;
  assign new_n56 = ~G53GAT;
  assign new_n57 = ~G60GAT;
  assign new_n58 = ~G63GAT;
  assign new_n59 = ~G66GAT;
  assign new_n60 = ~G73GAT;
  assign new_n61 = ~G76GAT;
  assign new_n62 = ~G79GAT;
  assign new_n63 = ~G86GAT;
  assign new_n64 = ~G89GAT;
  assign new_n65 = ~G92GAT;
  assign new_n66 = ~G99GAT;
  assign new_n67 = ~G102GAT;
  assign new_n68 = ~G105GAT;
  assign new_n69 = ~G112GAT;
  assign new_n70 = ~G115GAT;
  assign new_n71 = new_n46 & G17GAT;
  assign new_n72 = ~new_n71;
  assign new_n73 = new_n61 & G82GAT;
  assign new_n74 = ~new_n73;
  assign new_n75 = new_n72 & new_n74;
  assign new_n76 = new_n55 & G56GAT;
  assign new_n77 = ~new_n76;
  assign new_n78 = new_n44 & G4GAT;
  assign new_n79 = ~new_n78;
  assign new_n80 = new_n77 & new_n79;
  assign new_n81 = new_n52 & G43GAT;
  assign new_n82 = ~new_n81;
  assign new_n83 = new_n49 & G30GAT;
  assign new_n84 = ~new_n83;
  assign new_n85 = new_n82 & new_n84;
  assign new_n86 = new_n58 & G69GAT;
  assign new_n87 = ~new_n86;
  assign new_n88 = new_n64 & G95GAT;
  assign new_n89 = ~new_n88;
  assign new_n90 = new_n87 & new_n89;
  assign new_n91 = new_n67 & G108GAT;
  assign new_n92 = ~new_n91;
  assign new_n93 = new_n90 & new_n92;
  assign new_n94 = new_n85 & new_n93;
  assign new_n95 = new_n80 & new_n94;
  assign new_n96 = new_n75 & new_n95;
  assign G223GAT = ~new_n96;
  assign new_n98 = G102GAT & G223GAT;
  assign new_n99 = ~new_n98;
  assign new_n100 = G108GAT & new_n99;
  assign new_n101 = ~new_n100;
  assign new_n102 = new_n69 & new_n100;
  assign new_n103 = ~new_n102;
  assign new_n104 = G63GAT & G223GAT;
  assign new_n105 = ~new_n104;
  assign new_n106 = G69GAT & new_n105;
  assign new_n107 = new_n60 & new_n106;
  assign new_n108 = ~new_n107;
  assign new_n109 = new_n103 & new_n108;
  assign new_n110 = G76GAT & G223GAT;
  assign new_n111 = ~new_n110;
  assign new_n112 = G82GAT & new_n111;
  assign new_n113 = new_n63 & new_n112;
  assign new_n114 = ~new_n113;
  assign new_n115 = G37GAT & G223GAT;
  assign new_n116 = ~new_n115;
  assign new_n117 = G43GAT & new_n116;
  assign new_n118 = new_n54 & new_n117;
  assign new_n119 = ~new_n118;
  assign new_n120 = new_n114 & new_n119;
  assign new_n121 = G50GAT & G223GAT;
  assign new_n122 = ~new_n121;
  assign new_n123 = G56GAT & new_n122;
  assign new_n124 = new_n57 & new_n123;
  assign new_n125 = ~new_n124;
  assign new_n126 = new_n120 & new_n125;
  assign new_n127 = G89GAT & G223GAT;
  assign new_n128 = ~new_n127;
  assign new_n129 = G95GAT & new_n128;
  assign new_n130 = new_n66 & new_n129;
  assign new_n131 = ~new_n130;
  assign new_n132 = G11GAT & G223GAT;
  assign new_n133 = ~new_n132;
  assign new_n134 = G17GAT & new_n133;
  assign new_n135 = new_n48 & new_n134;
  assign new_n136 = ~new_n135;
  assign new_n137 = new_n131 & new_n136;
  assign new_n138 = G1GAT & G223GAT;
  assign new_n139 = ~new_n138;
  assign new_n140 = G4GAT & new_n139;
  assign new_n141 = new_n45 & new_n140;
  assign new_n142 = ~new_n141;
  assign new_n143 = G24GAT & G223GAT;
  assign new_n144 = ~new_n143;
  assign new_n145 = G30GAT & new_n144;
  assign new_n146 = new_n51 & new_n145;
  assign new_n147 = ~new_n146;
  assign new_n148 = new_n142 & new_n147;
  assign new_n149 = new_n137 & new_n148;
  assign new_n150 = new_n126 & new_n149;
  assign new_n151 = new_n109 & new_n150;
  assign G329GAT = ~new_n151;
  assign new_n153 = new_n68 & new_n130;
  assign new_n154 = ~new_n153;
  assign new_n155 = new_n47 & new_n141;
  assign new_n156 = ~new_n155;
  assign new_n157 = new_n154 & new_n156;
  assign new_n158 = new_n70 & new_n102;
  assign new_n159 = ~new_n158;
  assign new_n160 = new_n53 & new_n146;
  assign new_n161 = ~new_n160;
  assign new_n162 = new_n159 & new_n161;
  assign new_n163 = new_n50 & new_n135;
  assign new_n164 = ~new_n163;
  assign new_n165 = new_n162 & new_n164;
  assign new_n166 = new_n157 & new_n165;
  assign new_n167 = new_n50 & new_n134;
  assign new_n168 = ~new_n167;
  assign new_n169 = new_n70 & new_n100;
  assign new_n170 = ~new_n169;
  assign new_n171 = new_n168 & new_n170;
  assign new_n172 = new_n47 & new_n140;
  assign new_n173 = ~new_n172;
  assign new_n174 = new_n68 & new_n129;
  assign new_n175 = ~new_n174;
  assign new_n176 = new_n173 & new_n175;
  assign new_n177 = new_n171 & new_n176;
  assign new_n178 = new_n53 & new_n145;
  assign new_n179 = ~new_n178;
  assign new_n180 = new_n177 & new_n179;
  assign new_n181 = ~new_n180;
  assign new_n182 = new_n151 & new_n181;
  assign new_n183 = ~new_n182;
  assign new_n184 = G86GAT & G329GAT;
  assign new_n185 = ~new_n184;
  assign new_n186 = new_n112 & new_n185;
  assign new_n187 = new_n65 & new_n186;
  assign new_n188 = ~new_n187;
  assign new_n189 = new_n183 & new_n188;
  assign new_n190 = new_n166 & new_n189;
  assign new_n191 = G47GAT & G329GAT;
  assign new_n192 = ~new_n191;
  assign new_n193 = new_n117 & new_n192;
  assign new_n194 = new_n56 & new_n193;
  assign new_n195 = ~new_n194;
  assign new_n196 = new_n190 & new_n195;
  assign new_n197 = G73GAT & G329GAT;
  assign new_n198 = ~new_n197;
  assign new_n199 = new_n106 & new_n198;
  assign new_n200 = ~new_n199;
  assign new_n201 = new_n62 & new_n199;
  assign new_n202 = ~new_n201;
  assign new_n203 = G60GAT & G329GAT;
  assign new_n204 = ~new_n203;
  assign new_n205 = new_n123 & new_n204;
  assign new_n206 = ~new_n205;
  assign new_n207 = new_n59 & new_n205;
  assign new_n208 = ~new_n207;
  assign new_n209 = new_n202 & new_n208;
  assign new_n210 = new_n196 & new_n209;
  assign G370GAT = ~new_n210;
  assign new_n212 = G8GAT & G329GAT;
  assign new_n213 = ~new_n212;
  assign new_n214 = G14GAT & G370GAT;
  assign new_n215 = ~new_n214;
  assign new_n216 = new_n213 & new_n215;
  assign new_n217 = new_n140 & new_n216;
  assign new_n218 = ~new_n217;
  assign new_n219 = G99GAT & G329GAT;
  assign new_n220 = ~new_n219;
  assign new_n221 = G105GAT & G370GAT;
  assign new_n222 = ~new_n221;
  assign new_n223 = new_n220 & new_n222;
  assign new_n224 = new_n129 & new_n223;
  assign new_n225 = ~new_n224;
  assign new_n226 = G53GAT & G370GAT;
  assign new_n227 = ~new_n226;
  assign new_n228 = new_n193 & new_n227;
  assign new_n229 = ~new_n228;
  assign new_n230 = G66GAT & G370GAT;
  assign new_n231 = ~new_n230;
  assign new_n232 = new_n205 & new_n231;
  assign new_n233 = ~new_n232;
  assign new_n234 = new_n229 & new_n233;
  assign new_n235 = G40GAT & G370GAT;
  assign new_n236 = ~new_n235;
  assign new_n237 = new_n145 & new_n236;
  assign new_n238 = G34GAT & G329GAT;
  assign new_n239 = ~new_n238;
  assign new_n240 = new_n237 & new_n239;
  assign new_n241 = ~new_n240;
  assign new_n242 = G27GAT & G370GAT;
  assign new_n243 = ~new_n242;
  assign new_n244 = new_n134 & new_n243;
  assign new_n245 = G21GAT & G329GAT;
  assign new_n246 = ~new_n245;
  assign new_n247 = new_n244 & new_n246;
  assign new_n248 = ~new_n247;
  assign new_n249 = new_n241 & new_n248;
  assign new_n250 = new_n234 & new_n249;
  assign G430GAT = ~new_n250;
  assign new_n252 = new_n225 & new_n250;
  assign new_n253 = G92GAT & G370GAT;
  assign new_n254 = ~new_n253;
  assign new_n255 = new_n186 & new_n254;
  assign new_n256 = ~new_n255;
  assign new_n257 = new_n252 & new_n256;
  assign new_n258 = new_n101 & new_n200;
  assign new_n259 = new_n257 & new_n258;
  assign new_n260 = ~new_n259;
  assign G421GAT = new_n218 & new_n260;
  assign new_n262 = G79GAT & G370GAT;
  assign new_n263 = ~new_n262;
  assign new_n264 = new_n199 & new_n263;
  assign new_n265 = ~new_n264;
  assign new_n266 = new_n256 & new_n265;
  assign new_n267 = ~new_n266;
  assign new_n268 = new_n234 & new_n267;
  assign new_n269 = ~new_n268;
  assign new_n270 = new_n249 & new_n269;
  assign G431GAT = ~new_n270;
  assign new_n272 = G66GAT & new_n201;
  assign new_n273 = ~new_n272;
  assign new_n274 = new_n224 & new_n256;
  assign new_n275 = ~new_n274;
  assign new_n276 = new_n206 & new_n264;
  assign new_n277 = ~new_n276;
  assign new_n278 = new_n275 & new_n277;
  assign new_n279 = new_n229 & new_n278;
  assign new_n280 = new_n273 & new_n279;
  assign new_n281 = ~new_n280;
  assign new_n282 = new_n241 & new_n281;
  assign new_n283 = ~new_n282;
  assign new_n284 = new_n248 & new_n283;
  assign G432GAT = ~new_n284;
endmodule


