#!/usr/bin/env ruby

require "json"

abort("Missing -rd input_json=...") unless defined?($input_json) && $input_json
abort("Missing -rd output_gds=...") unless defined?($output_gds) && $output_gds

top_cell_name = defined?($top_cell) && $top_cell ? $top_cell : "TOP"
dbu = if defined?($dbu) && $dbu
        $dbu.to_f
      else
        0.001
      end

layer_map = {
  "li1" => [67, 20],
  "met1" => [68, 20],
  "met2" => [69, 20],
  "met3" => [70, 20],
  "met4" => [71, 20],
  "met5" => [72, 20]
}

if defined?($layer_map_json) && $layer_map_json
  loaded = JSON.parse(File.read($layer_map_json))
  layer_map = {}
  loaded.each do |name, pair|
    layer_map[name.to_s.downcase] = [Integer(pair[0]), Integer(pair[1])]
  end
end

data = JSON.parse(File.read($input_json))
lpl = data["lpl"] || []

layout = RBA::Layout::new
layout.dbu = dbu
top = layout.create_cell(top_cell_name)

lpl.each_with_index do |poly, idx|
  layer_name = poly.fetch("layer").to_s.downcase
  layer_pair = layer_map[layer_name]
  abort("Unknown layer '#{layer_name}' at polygon #{idx}") unless layer_pair

  points_raw = poly.fetch("points")
  points = points_raw.map { |xy| RBA::Point::new(Integer(xy[0]), Integer(xy[1])) }
  if points.length >= 2 && points.first == points.last
    points = points[0...-1]
  end
  abort("Polygon #{idx} has fewer than 3 unique points") if points.length < 3

  layer_index = layout.layer(Integer(layer_pair[0]), Integer(layer_pair[1]))
  top.shapes(layer_index).insert(RBA::Polygon::new(points))
end

labels = data["labels"] || []
labels.each_with_index do |label, idx|
  layer_name = label.fetch("layer").to_s.downcase
  layer_pair = layer_map[layer_name]
  abort("Unknown layer '#{layer_name}' at label #{idx}") unless layer_pair
  text = label.fetch("text")
  abort("Invalid text at label #{idx}") unless text.is_a?(String) && !text.empty? && !text.include?("\0")
  position = label.fetch("position")
  abort("Invalid position at label #{idx}") unless position.length == 2 && position.all? { |v| v.is_a?(Integer) }
  layer_index = layout.layer(Integer(layer_pair[0]), Integer(layer_pair[1]))
  top.shapes(layer_index).insert(RBA::Text.new(text, RBA::Trans.new(position[0], position[1])))
end

layout.write($output_gds)
puts "Wrote #{$output_gds} with #{lpl.length} polygons"
