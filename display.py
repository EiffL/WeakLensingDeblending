#!/usr/bin/env python
"""Display simulated images and analysis results generated by the simulate program.
"""

import argparse

import numpy as np
import numpy.ma

import matplotlib.pyplot as plt
import matplotlib.collections

import descwl

def main():
    # Initialize and parse command-line arguments.
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--verbose', action = 'store_true',
        help = 'Provide verbose output.')
    descwl.output.Reader.add_args(parser)
    parser.add_argument('--no-display', action = 'store_true',
        help = 'Do not display the image on screen.')
    parser.add_argument('-o','--output-name',type = str, default = None, metavar = 'FILE',
        help = 'Name of the output file to write.')

    select_group = parser.add_argument_group('Object selection options')
    select_group.add_argument('--galaxy', type = int, action = 'append',
        default = [ ], metavar = 'ID',
        help = 'Select the galaxy with this database ID (can be repeated).')
    select_group.add_argument('--group', type = int, action = 'append',
        default = [ ], metavar = 'ID',
        help = 'Select galaxies belonging to the group with this group ID (can be repeated).')
    select_group.add_argument('--select', type = str, action = 'append',
        default = [ ], metavar = 'CUT',
        help = 'Select objects passing the specified cut (can be repeated).')

    display_group = parser.add_argument_group('Display options')
    display_group.add_argument('--crop', action = 'store_true',
        help = 'Crop the displayed pixels around the selected objects.')
    display_group.add_argument('--draw-moments', action = 'store_true',
        help = 'Draw ellipses to represent the 50% iosophote second moments of selected objects.')
    display_group.add_argument('--annotate', action = 'store_true',
        help = 'Annotate selected objects with a brief description.')
    display_group.add_argument('--annotate-format', type = str,
        default = 'z=%(z).1f\nAB=%(ab_mag).1f', metavar = 'FMT',
        help = 'String interpolation format to generate annotation labels.')
    display_group.add_argument('--annotate-size', type = str,
        default = 'medium', metavar = 'SIZE',
        help = 'Matplotlib font size specification in points or relative (small,large,...)')
    display_group.add_argument('--no-crosshair', action = 'store_true',
        help = 'Do not draw a crosshair at the centroid of each selected object.')
    display_group.add_argument('--dpi', type = float, default = 64.,
        help = 'Number of pixels per inch to use for display.')
    display_group.add_argument('--magnification', type = float,
        default = 1, metavar = 'MAG',
        help = 'Magnification factor to use for display.')
    display_group.add_argument('--max-view-size', type = int,
        default = 2048, metavar = 'SIZE',
        help = 'Maximum allowed pixel dimensions of displayed image.')
    display_group.add_argument('--colormap', type = str,
        default = 'Blues', metavar = 'CMAP',
        help = 'Matplotlib colormap name to use for background pixel values.')
    display_group.add_argument('--highlight', type = str,
        default = 'hot_r', metavar = 'CMAP',
        help = 'Matplotlib colormap name to use for highlighted pixel values.')
    display_group.add_argument('--crosshair-color', type = str,
        default = 'greenyellow', metavar = 'COL',
        help = 'Matplotlib color name to use for crosshairs.')
    display_group.add_argument('--ellipse-color', type = str,
        default = 'greenyellow', metavar = 'COL',
        help = 'Matplotlib color name to use for second-moment ellipses.')
    display_group.add_argument('--annotate-color', type = str,
        default = 'green', metavar = 'COL',
        help = 'Matplotlib color name to use for annotation text.')
    display_group.add_argument('--clip-lo-percentile', type = float,
        default = 0.0, metavar = 'PCT',
        help = 'Clip pixels with values below this percentile for the image.')
    display_group.add_argument('--clip-hi-percentile', type = float,
        default = 90.0, metavar = 'PCT',
        help = 'Clip pixels with values above this percentile for the image.')
    display_group.add_argument('--hide-background', action = 'store_true',
        help = 'Do not display background pixels.')

    args = parser.parse_args()
    if args.no_display and not args.output_name:
        print 'No display our output requested.'
        return 0

    # Load the analysis results file we will display from.
    try:
        reader = descwl.output.Reader.from_args(args)
        results = reader.results
        if args.verbose:
            print results.survey.description()
    except RuntimeError,e:
        print str(e)
        return -1

    # Perform object selection.
    if args.select:
        # Combine select clauses with logical AND.
        selection = results.select('ALL')
        for selector in args.select:
            selection = np.logical_and(selection,results.select(selector))
    else:
        # Nothing is selected by default.
        selection = results.select('NONE')
    # Add any specified groups to the selection.
    for identifier in args.group:
        selected = results.select('grp_id==%d' % identifier)
        if not np.any(selected):
            print 'WARNING: no group found with ID %d.' % identifier
        selection = np.logical_or(selection,selected)
    # Add any specified galaxies to the selection.
    for identifier in args.galaxy:
        selected = results.select('db_id==%d' % identifier)
        if not np.any(selected):
            print 'WARNING: no galaxy found with ID %d.' % identifier
        selection = np.logical_or(selection,selected)
    selected_indices = np.arange(results.num_objects)[selection]

    # Build the image of selected objects.
    selected_image = results.get_subimage(selected_indices)

    # Prepare the z scaling.
    zscale_pixels = results.survey.image.array
    if selected_image:
        if selected_image.bounds.area() < 16:
            print 'WARNING: using full image for z-scaling since only %d pixel(s) selected.' % (
                selected_image.bounds.area())
        else:
            zscale_pixels = selected_image.array
    non_zero_pixels = (zscale_pixels != 0)
    vmin,vmax = np.percentile(zscale_pixels[non_zero_pixels],
        q = (args.clip_lo_percentile,args.clip_hi_percentile))

    def znorm(pixels):
        return (np.clip(pixels,vmin,vmax) - vmin)/(vmax-vmin)

    # See http://ds9.si.edu/ref/how.html#Scales
    def zscale(pixels):
        return np.sqrt(znorm(pixels))

    # Calculate our viewing bounds.
    if args.crop and selected_image is not None:
        view_bounds = selected_image.bounds
    else:
        view_bounds = results.survey.image.bounds

    # Initialize a matplotlib figure to display our view bounds.
    view_width = view_bounds.xmax - view_bounds.xmin + 1
    view_height = view_bounds.ymax - view_bounds.ymin + 1
    if (view_width*args.magnification > args.max_view_size or
        view_height*args.magnification > args.max_view_size):
        print 'Requested view dimensions %d x %d too big. Increase --max-view-size if necessary.' % (
            view_width*args.magnification,view_height*args.magnification)
        return -1
    fig_height = args.magnification*(view_height/args.dpi)
    fig_width = args.magnification*(view_width/args.dpi)
    figure = plt.figure(figsize = (fig_width,fig_height),frameon = False,dpi = args.dpi)
    axes = plt.Axes(figure, [0., 0., 1., 1.])
    axes.axis(xmin=view_bounds.xmin,xmax=view_bounds.xmax+1,
        ymin=view_bounds.ymin,ymax=view_bounds.ymax+1)
    axes.set_axis_off()
    figure.add_axes(axes)

    def show_image(image,masked,**kwargs):
        overlap = image.bounds & view_bounds
        xlo = overlap.xmin
        xhi = overlap.xmax + 1
        ylo = overlap.ymin
        yhi = overlap.ymax + 1
        overlap_pixels = image[overlap].array
        z = zscale(overlap_pixels)
        if masked:
            # Only show non-zero pixels.
            z = numpy.ma.masked_where(overlap_pixels == 0,z)
        axes.imshow(z,extent = (xlo,xhi,ylo,yhi),
            aspect = 'equal',origin = 'lower',interpolation = 'nearest',**kwargs)

    # Plot the full simulated image using the background colormap.
    if not args.hide_background:
        show_image(results.survey.image,masked = False,cmap = args.colormap)

    # Overplot the selected objects showing only non-zero pixels.
    if selected_image:
        show_image(selected_image,masked = True,cmap = args.highlight)

    # The argparse module escapes any \n or \t in string args, but we need these
    # to be unescaped in the annotation format string.
    args.annotate_format = args.annotate_format.decode('string-escape')

    scale = results.survey.pixel_scale
    num_selected = len(selected_indices)
    ellipse_centers = np.empty((num_selected,2))
    ellipse_widths = np.empty(num_selected)
    ellipse_heights = np.empty(num_selected)
    ellipse_angles = np.empty(num_selected)
    for index,selected in enumerate(selected_indices):
        info = results.table[selected]
        # Calculate the selected object's centroid position in user display coordinates.
        x_center = (0.5*results.survey.image_width + info['dx']/scale)
        y_center = (0.5*results.survey.image_height + info['dy']/scale)
        # Draw a crosshair at the centroid of selected objects.
        if not args.no_crosshair:
            axes.plot(x_center,y_center,'+',color = args.crosshair_color,
                markeredgewidth = 2,markersize = 24)
        # Add annotation text if requested.
        if args.annotate:
            annotation = args.annotate_format % info
            axes.annotate(annotation,xy = (x_center,y_center),xytext = (4,4),
                textcoords = 'offset points',color = args.annotate_color,
                fontsize = args.annotate_size)
        # Add a second-moments ellipse if requested.
        if args.draw_moments:
            ellipse_centers[index] = (x_center,y_center)
            ellipse_widths[index] = info['a']/scale
            ellipse_heights[index] = info['b']/scale
            ellipse_angles[index] = np.degrees(info['beta'])

    # Draw any ellipses.
    if args.draw_moments:
        ellipses = matplotlib.collections.EllipseCollection(units = 'x',
            widths = ellipse_widths,heights = ellipse_heights,angles = ellipse_angles,
            offsets = ellipse_centers, transOffset = axes.transData)
        ellipses.set_facecolor('none')
        ellipses.set_edgecolor(args.ellipse_color)
        axes.add_collection(ellipses,autolim = True)

    if args.output_name:
        figure.savefig(args.output_name,dpi = args.dpi)

    if not args.no_display:
        plt.show()

if __name__ == '__main__':
    main()
