include RBA

input_gds = ($input_gds || "").to_s
output_png = ($output_png || "").to_s
width = (($width || "1600").to_s).to_i
height = (($height || "1600").to_s).to_i
editable = (($editable || "false").to_s == "true")

if input_gds.empty? || output_png.empty?
  raise "Both -rd input_gds=... and -rd output_png=... are required"
end

view = RBA::LayoutView::new(editable)
view.load_layout(input_gds, false)
view.max_hier
view.zoom_fit
view.save_image(output_png, width, height)
